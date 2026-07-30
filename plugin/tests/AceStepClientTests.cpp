#include "AceStepClient.h"
#include "StubAceStepServer.h"

namespace acemusic
{

class AceStepClientTests final : public juce::UnitTest
{
public:
    AceStepClientTests()
        : juce::UnitTest ("AceStepClient", "acemusic")
    {
    }

    void runTest() override
    {
        beginTest ("parses the {data:{models:[{name}]}} envelope");
        {
            const auto names = parseModelNames (
                R"({"data":{"models":[{"name":"a"},{"name":"b"}],"jobs":{}},"code":200})");

            expectEquals (names.size(), 2);
            expectEquals (names[0], juce::String ("a"));
            expectEquals (names[1], juce::String ("b"));
        }

        beginTest ("parses a bare payload with no data wrapper");
        {
            const auto names = parseModelNames (R"({"models":[{"name":"solo"}]})");
            expectEquals (names.size(), 1);
            expectEquals (names[0], juce::String ("solo"));
        }

        beginTest ("survives malformed and empty bodies");
        {
            expectEquals (parseModelNames ("not json at all").size(), 0);
            expectEquals (parseModelNames ("").size(), 0);
            expectEquals (parseModelNames ("{}").size(), 0);
            expectEquals (parseModelNames (R"({"data":{"models":"nope"}})").size(), 0);
            expectEquals (parseModelNames (R"({"data":{"models":[{"noname":1}]}})").size(), 0);
        }

        beginTest ("probes a live server: reports models and sends the Bearer header");
        {
            test::StubAceStepServer server;
            const auto port = server.start();
            expect (port != 0, "could not bind a stub server port");

            const auto result = probeAceStepServer (server.getBaseUrl(), "secret-key");

            expect (result.ok, "probe failed: " + result.errorMessage);
            expect (! result.cancelled);
            expectEquals (result.models.size(), 2);
            expectEquals (result.models[0], juce::String ("ace-step-1.5"));
            expectEquals (result.models[1], juce::String ("ace-step-mini"));

            const auto request = server.getLastRequest();
            expect (request.contains ("/v1/stats"),
                    "probe did not request /v1/stats — got: " + request.upToFirstOccurrenceOf ("\r\n", false, false));
            expect (request.contains ("Authorization: Bearer secret-key"),
                    "Authorization header was not sent");
        }

        beginTest ("omits the Authorization header when no API key is set");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto result = probeAceStepServer (server.getBaseUrl(), "");

            expect (result.ok, result.errorMessage);
            expect (! server.getLastRequest().contains ("Authorization"),
                    "sent an Authorization header despite having no key");
        }

        beginTest ("tolerates a trailing slash on the base URL");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto result = probeAceStepServer (server.getBaseUrl() + "/", "");

            expect (result.ok, result.errorMessage);
            expect (! server.getLastRequest().contains ("//v1/stats"), "built a double-slashed path");
        }

        beginTest ("server stopped: reports 'Server unreachable'");
        {
            const auto closedPort = test::findClosedPort();
            expect (closedPort != 0, "could not find a closed port");

            const auto result = probeAceStepServer ("http://127.0.0.1:" + juce::String (closedPort), "");

            expect (! result.ok, "probe claimed success against a closed port");
            expect (! result.cancelled);
            expectEquals (result.errorMessage, juce::String ("Server unreachable"));
            expectEquals (result.models.size(), 0);
        }

        beginTest ("non-2xx status is reported with the code");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 500 Internal Server Error");
            server.setResponseBody ("{}");

            const auto result = probeAceStepServer (server.getBaseUrl(), "");

            expect (! result.ok);
            expect (result.errorMessage.contains ("500"),
                    "did not surface the status code, got: " + result.errorMessage);
        }

        beginTest ("401/403 point at the API key rather than a generic failure");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 401 Unauthorized");
            server.setResponseBody ("{}");

            const auto withoutKey = probeAceStepServer (server.getBaseUrl(), "");
            expect (! withoutKey.ok);
            expectEquals (withoutKey.errorMessage, juce::String ("Server requires an API key"));

            const auto withKey = probeAceStepServer (server.getBaseUrl(), "wrong-key");
            expect (! withKey.ok);
            expectEquals (withKey.errorMessage, juce::String ("API key rejected by the server"));
        }

        beginTest ("a 2xx with no models is an error, not a false green");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseBody (R"({"data":{"models":[]}})");

            const auto result = probeAceStepServer (server.getBaseUrl(), "");

            expect (! result.ok, "reported success for a server with no models");
            expect (result.errorMessage.contains ("no models"), result.errorMessage);
        }

        beginTest ("rejects an empty or non-http URL without touching the network");
        {
            const auto empty = probeAceStepServer ("", "");
            expect (! empty.ok);
            expectEquals (empty.errorMessage, juce::String ("No server URL set"));

            const auto bare = probeAceStepServer ("localhost:8001", "");
            expect (! bare.ok, "accepted a URL with no scheme");
        }

        beginTest ("returns cancelled, not an error, when asked to stop");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto result = probeAceStepServer (server.getBaseUrl(), "", [] { return true; });

            expect (result.cancelled, "did not report cancellation");
            expect (! result.ok);
            expect (result.errorMessage.isEmpty(), "surfaced an error for a cancellation");
            expectEquals (server.getRequestCount(), 0, "connected despite being cancelled up front");
        }
    }
};

static AceStepClientTests aceStepClientTests;

} // namespace acemusic
