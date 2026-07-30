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
        signalThreadShouldExit();
        listener.close();
        stopThread (2000);
    }

    int getPort() const noexcept                   { return port; }
    juce::String getBaseUrl() const                { return "http://127.0.0.1:" + juce::String (port); }

    /** Full response body to return. */
    void setResponseBody (const juce::String& body)      { const juce::ScopedLock sl (lock); responseBody = body; }
    void setStatusLine (const juce::String& line)        { const juce::ScopedLock sl (lock); statusLine = line; }

    /** Holds the response back, so a test can observe a probe while it is in flight. */
    void setResponseDelayMs (int ms)                     { responseDelayMs = ms; }

    /** The request line + headers of the most recent request. */
    juce::String getLastRequest() const                  { const juce::ScopedLock sl (lock); return lastRequest; }
    int getRequestCount() const noexcept                 { return requestCount.load(); }

private:
    void run() override
    {
        while (! threadShouldExit())
        {
            std::unique_ptr<juce::StreamingSocket> connection (listener.waitForNextConnection());

            if (connection == nullptr)
                continue;   // listener closed, or a transient accept failure

            char buffer[8192] = {};
            const auto bytesRead = connection->read (buffer, sizeof (buffer) - 1, false);

            juce::String body, status;
            {
                const juce::ScopedLock sl (lock);

                if (bytesRead > 0)
                    lastRequest = juce::String::fromUTF8 (buffer, bytesRead);

                body = responseBody;
                status = statusLine;
            }

            ++requestCount;

            if (const auto delay = responseDelayMs.load(); delay > 0)
            {
                // Sliced so stopping the server doesn't have to wait out the delay.
                for (int waited = 0; waited < delay && ! threadShouldExit(); waited += 20)
                    juce::Thread::sleep (juce::jmin (20, delay - waited));
            }

            const auto response = status + "\r\n"
                                + "Content-Type: application/json\r\n"
                                + "Content-Length: " + juce::String (body.getNumBytesAsUTF8()) + "\r\n"
                                + "Connection: close\r\n\r\n"
                                + body;

            connection->write (response.toRawUTF8(), (int) response.getNumBytesAsUTF8());
            connection->close();
        }
    }

    juce::StreamingSocket listener;
    int port = 0;
    std::atomic<int> requestCount { 0 };
    std::atomic<int> responseDelayMs { 0 };

    mutable juce::CriticalSection lock;
    juce::String lastRequest;
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
