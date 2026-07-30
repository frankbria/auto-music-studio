#pragma once

#include <juce_core/juce_core.h>

#include <atomic>

namespace acemusic::test
{

/**
    A real HTTP server on a real loopback socket, serving canned ACE-Step responses.

    Not a mock: the plugin's WebInputStream does an actual TCP connect, sends actual
    request bytes, and parses an actual response. That is what makes these tests worth
    anything — a mocked client would have passed even with US-23.1's curl-free
    WebInputStream broken.

    Serves one request per connection, `Connection: close`, and keeps accepting until
    stopped.
*/
class StubAceStepServer final : private juce::Thread
{
public:
    StubAceStepServer() : juce::Thread ("stub-acestep") {}

    ~StubAceStepServer() override
    {
        stop();
    }

    /** Binds to an ephemeral-ish port and starts serving.
        @returns the port, or 0 if no port in the scan range was free. */
    int start()
    {
        // Scan rather than hardcode: parallel CI jobs on one runner would collide.
        for (int candidate = 18200; candidate < 18300; ++candidate)
        {
            if (listener.createListener (candidate, "127.0.0.1"))
            {
                port = candidate;
                startThread();
                return port;
            }
        }

        return 0;
    }

    void stop()
    {
        // Order matters: the accept loop polls for readability with a short timeout
        // rather than blocking in waitForNextConnection(), because close() does NOT
        // reliably unblock a blocked accept on macOS or Windows. Relying on it made
        // every teardown burn the full stopThread timeout there and left threads
        // running into the next test.
        signalThreadShouldExit();
        stopThread (3000);
        listener.close();
    }

    int getPort() const noexcept                   { return port; }
    juce::String getBaseUrl() const                { return "http://127.0.0.1:" + juce::String (port); }

    /** Full response body to return. */
    void setResponseBody (const juce::String& body)      { const juce::ScopedLock sl (lock); responseBody = body; }
    void setStatusLine (const juce::String& line)        { const juce::ScopedLock sl (lock); statusLine = line; }

    /** Makes the server sit on its response until releaseResponse() is called, so a
        test can observe a probe while it is genuinely in flight.

        Deliberately a signal rather than a sleep. The client-side cost of a stalled
        response is platform-dependent: measured on macOS CI, a probe takes roughly
        the stall plus ~800ms, against a 2s timeout (a 200ms stall came back in
        1031ms; 700ms and 1500ms both hit the timeout and failed). Gating on a signal
        keeps the in-flight window bounded by what the test does, not by a duration
        that has to be tuned per platform. */
    void holdResponse()
    {
        releaseEvent.reset();
        holding = true;
    }

    /** Lets a held response go. Safe to call even if nothing is held. */
    void releaseResponse()
    {
        holding = false;
        releaseEvent.signal();
    }

    /** The request line + headers of the most recent request. */
    juce::String getLastRequest() const                  { const juce::ScopedLock sl (lock); return lastRequest; }
    int getRequestCount() const noexcept                 { return requestCount.load(); }

    /** Body of the most recent request, i.e. everything after the blank line. */
    juce::String getLastBody() const                     { const juce::ScopedLock sl (lock); return lastBody; }

    /** Path of the most recent request, e.g. "/release_task". */
    juce::String getLastPath() const                     { const juce::ScopedLock sl (lock); return lastPath; }

    /** Serve `body` for requests whose path contains `pathFragment`, overriding the
        default response. Lets one stub stand in for the whole submit/poll/download
        sequence. */
    void setResponseFor (const juce::String& pathFragment, const juce::String& body)
    {
        const juce::ScopedLock sl (lock);
        routes.set (pathFragment, body);
    }

    /** Number of requests seen for paths containing `pathFragment`. */
    int getRequestCountFor (const juce::String& pathFragment) const
    {
        const juce::ScopedLock sl (lock);
        return pathCounts[pathFragment];
    }

    /** Body of the last request to a path containing `pathFragment`.

        Per-path, because getLastBody() is whatever arrived most recently — during a
        generation that is a poll, not the submit a test wants to assert on. */
    juce::String getBodyFor (const juce::String& pathFragment) const
    {
        const juce::ScopedLock sl (lock);
        return pathBodies[pathFragment];
    }

private:
    void run() override
    {
        while (! threadShouldExit())
        {
            // Poll instead of blocking in accept — see stop() for why.
            if (listener.waitUntilReady (true, 100) != 1)
                continue;   // 0 = nothing pending, -1 = closed or error

            std::unique_ptr<juce::StreamingSocket> connection (listener.waitForNextConnection());

            if (connection == nullptr)
                continue;   // listener closed, or a transient accept failure

            // Wait for the request bytes before reading. A non-blocking read straight
            // after accept returns 0 on macOS/Windows, where the request has not
            // necessarily landed yet — which silently left lastRequest empty and made
            // the header assertions fail while the response still went out fine.
            char buffer[8192] = {};
            int bytesRead = 0;

            if (connection->waitUntilReady (true, 3000) == 1)
                bytesRead = connection->read (buffer, sizeof (buffer) - 1, false);

            juce::String body, status;
            {
                const juce::ScopedLock sl (lock);

                if (bytesRead > 0)
                {
                    const auto whole = juce::String::fromUTF8 (buffer, bytesRead);
                    lastRequest = whole.upToFirstOccurrenceOf ("\r\n\r\n", false, false);
                    lastBody    = whole.fromFirstOccurrenceOf ("\r\n\r\n", false, false);

                    // "POST /release_task HTTP/1.1" -> "/release_task"
                    const auto requestLine = whole.upToFirstOccurrenceOf ("\r\n", false, false);
                    lastPath = requestLine.fromFirstOccurrenceOf (" ", false, false)
                                          .upToFirstOccurrenceOf (" ", false, false);

                    pathCounts.set (lastPath, pathCounts[lastPath] + 1);
                    pathBodies.set (lastPath, lastBody);

                    for (auto& route : routes)
                    {
                        const auto fragment = route.name.toString();

                        if (lastPath.contains (fragment))
                        {
                            pathCounts.set (fragment, pathCounts[fragment] + 1);
                            pathBodies.set (fragment, lastBody);
                        }
                    }
                }

                body = responseBody;
                status = statusLine;

                for (auto& route : routes)
                {
                    if (lastPath.contains (route.name.toString()))
                    {
                        body = route.value.toString();
                        break;
                    }
                }
            }

            ++requestCount;

            // Sliced wait so stopping the server never blocks on a test that forgot
            // to release.
            while (holding.load() && ! threadShouldExit())
                releaseEvent.wait (50);

            const auto response = status + "\r\n"
                                + "Content-Type: application/json\r\n"
                                + "Content-Length: " + juce::String (body.getNumBytesAsUTF8()) + "\r\n"
                                + "Connection: close\r\n\r\n"
                                + body;

            connection->write (response.toRawUTF8(), (int) response.getNumBytesAsUTF8());

            // Let the client drain before closing. On Windows, closesocket() with the
            // default linger can discard unsent data, which would hand the plugin a
            // truncated body. waitUntilReady returns as soon as the peer closes its
            // end (readable EOF), so on loopback this normally costs microseconds —
            // the cap only matters for a client that waits for EOF despite the
            // Content-Length we send.
            connection->waitUntilReady (true, 150);
            connection->close();
        }
    }

    juce::StreamingSocket listener;
    int port = 0;
    std::atomic<int> requestCount { 0 };
    std::atomic<bool> holding { false };
    juce::WaitableEvent releaseEvent { true };   // manual reset

    mutable juce::CriticalSection lock;
    juce::String lastRequest, lastBody, lastPath;
    juce::NamedValueSet routes;
    mutable juce::HashMap<juce::String, int> pathCounts;
    mutable juce::HashMap<juce::String, juce::String> pathBodies;
    juce::String statusLine  { "HTTP/1.1 200 OK" };
    juce::String responseBody { R"({"data":{"models":[{"name":"ace-step-1.5"},{"name":"ace-step-mini"}],"jobs":{"running":0}},"code":200,"error":null})" };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (StubAceStepServer)
};

/** A port with nothing listening on it, for the "server stopped" cases. */
inline int findClosedPort()
{
    juce::StreamingSocket probe;

    for (int candidate = 18400; candidate < 18500; ++candidate)
    {
        if (probe.createListener (candidate, "127.0.0.1"))
        {
            // Bound it, so we know it was free — then release it and hand it back.
            probe.close();
            return candidate;
        }
    }

    return 0;
}

} // namespace acemusic::test
