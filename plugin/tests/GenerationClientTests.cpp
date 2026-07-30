#include "AceStepClient.h"
#include "GenerationRequest.h"
#include "StubAceStepServer.h"

namespace acemusic
{

/** submit / poll / download, against a real loopback HTTP server. */
class GenerationClientTests final : public juce::UnitTest
{
public:
    GenerationClientTests()
        : juce::UnitTest ("GenerationClient", "acemusic")
    {
    }

    static juce::String completedBody (const juce::String& files)
    {
        // `result` is a JSON *string* inside the envelope, exactly as ACE-Step sends
        // it — a plain nested array here would let a wrong parser pass.
        return "{\"data\":[{\"status\":1,\"result\":\"" + files.replace ("\"", "\\\"") + "\"}],\"code\":200}";
    }

    void runTest() override
    {
        beginTest ("submit returns the task id and posts the payload verbatim");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/release_task", R"({"data":{"task_id":"task-abc-123"},"code":200})");

            GenerationRequest request;
            request.prompt = "dark ambient drone";
            request.bpm = 90;

            const auto result = submitGeneration (server.getBaseUrl(), "", request.toPayloadJson());

            expect (result.ok, result.errorMessage);
            expectEquals (result.taskId, juce::String ("task-abc-123"));
            expectEquals (server.getLastPath(), juce::String ("/release_task"));

            // AC: "all parameter fields are sent correctly to the API (verified via
            // request logging)" — this is that verification.
            const auto sent = juce::JSON::parse (server.getLastBody());
            expect (sent.getDynamicObject() != nullptr, "body was not JSON: " + server.getLastBody());
            expectEquals (sent.getProperty ("prompt", juce::var()).toString(), juce::String ("dark ambient drone"));
            expectEquals ((int) sent.getProperty ("bpm", juce::var()), 90);
            expectEquals ((int) sent.getProperty ("batch_size", juce::var()), 2);
        }

        beginTest ("a POST carries BOTH the API key and the content type");
        {
            // withExtraHeaders appends rather than replaces (verified in JUCE's linux,
            // windows and mac implementations), so setting Content-Type after the
            // Authorization header keeps both. A cross-family review flagged the
            // opposite as critical; it was wrong, but it was right that nothing
            // covered it — every other test here runs without a key.
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/release_task", R"({"data":{"task_id":"t"},"code":200})");

            const auto result = submitGeneration (server.getBaseUrl(), "post-key", "{}");
            expect (result.ok, result.errorMessage);

            const auto request = server.getLastRequest();
            expect (request.contains ("Authorization: Bearer post-key"),
                    "the API key was lost on a POST:\n" + request);
            expect (request.containsIgnoreCase ("Content-Type: application/json"),
                    "the content type was lost on a POST:\n" + request);
        }

        beginTest ("a poll carries the API key too");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            const auto status = queryTask (server.getBaseUrl(), "poll-key", "t");
            expect (status.ok, status.errorMessage);
            expect (server.getLastRequest().contains ("Authorization: Bearer poll-key"),
                    "the API key was lost on a poll");
        }

        beginTest ("a download cut short is rejected, not saved as a clip");
        {
            // The server promises more than it sends; the read loop just ends, which
            // would otherwise move a truncated file into place and call it audio.
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setTruncatedResponse ("/v1/audio", "RIFF short", 999999);

            const auto destination = juce::File::getSpecialLocation (juce::File::tempDirectory)
                                         .getChildFile ("acemusic-truncated-"
                                                        + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)))
                                         .getChildFile ("clip.wav");

            const auto error = downloadAudio (server.getBaseUrl() + "/v1/audio?path=clip.wav", "", destination);

            expect (error.isNotEmpty(), "a truncated download was reported as success");
            expect (error.containsIgnoreCase ("cut short"), error);
            expect (! destination.existsAsFile(), "left a truncated file that looks like a clip");

            destination.getParentDirectory().deleteRecursively();
        }

        beginTest ("submit accepts either task_id or id");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/release_task", R"({"data":{"id":"legacy-id"},"code":200})");

            const auto result = submitGeneration (server.getBaseUrl(), "", "{}");
            expect (result.ok, result.errorMessage);
            expectEquals (result.taskId, juce::String ("legacy-id"));
        }

        beginTest ("submit reports a response with no task id rather than pretending");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/release_task", R"({"data":{},"code":200})");

            const auto result = submitGeneration (server.getBaseUrl(), "", "{}");
            expect (! result.ok, "claimed success with no task id");
            expect (result.errorMessage.containsIgnoreCase ("task id"), result.errorMessage);
        }

        beginTest ("submit surfaces an unreachable server");
        {
            const auto closedPort = test::findClosedPort();
            expect (closedPort != 0);

            const auto result = submitGeneration ("http://127.0.0.1:" + juce::String (closedPort), "", "{}");
            expect (! result.ok);
            expectEquals (result.errorMessage, juce::String ("Server unreachable"));
        }

        beginTest ("status 0/1/2 map to pending/completed/failed");
        {
            const juce::String base { "http://127.0.0.1:8001" };

            const auto pending = parseTaskStatus (R"({"data":[{"status":0}],"code":200})", base);
            expect (pending.ok);
            expect (pending.state == TaskStatus::State::pending);

            const auto done = parseTaskStatus (completedBody (R"([{"file":"/v1/audio?path=a.wav"}])"), base);
            expect (done.ok);
            expect (done.state == TaskStatus::State::completed);

            const auto failed = parseTaskStatus (R"({"data":[{"status":2,"error":"out of memory"}],"code":200})", base);
            expect (failed.ok, "the query itself succeeded");
            expect (failed.state == TaskStatus::State::failed);
            expectEquals (failed.errorMessage, juce::String ("out of memory"));
        }

        beginTest ("string statuses are tolerated, as the Python client does");
        {
            const juce::String base { "http://127.0.0.1:8001" };

            expect (parseTaskStatus (R"({"data":[{"status":"completed"}],"code":200})", base).state
                        == TaskStatus::State::completed);
            expect (parseTaskStatus (R"({"data":[{"status":"failed"}],"code":200})", base).state
                        == TaskStatus::State::failed);
            expect (parseTaskStatus (R"({"data":[{"status":"pending"}],"code":200})", base).state
                        == TaskStatus::State::pending);
        }

        beginTest ("the JSON-string result field is unpacked into absolute URLs");
        {
            const juce::String base { "http://127.0.0.1:8001" };
            const auto status = parseTaskStatus (
                completedBody (R"([{"file":"/v1/audio?path=one.wav"},{"file":"/v1/audio?path=two.wav"}])"),
                base);

            expectEquals (status.audioUrls.size(), 2);
            expectEquals (status.audioUrls[0], base + "/v1/audio?path=one.wav");
            expectEquals (status.audioUrls[1], base + "/v1/audio?path=two.wav");
        }

        beginTest ("an already-absolute file URL is left alone");
        {
            const auto status = parseTaskStatus (
                completedBody (R"([{"file":"http://elsewhere:9000/v1/audio?path=x.wav"}])"),
                "http://127.0.0.1:8001");

            expectEquals (status.audioUrls.size(), 1);
            expectEquals (status.audioUrls[0], juce::String ("http://elsewhere:9000/v1/audio?path=x.wav"));
        }

        beginTest ("a malformed result string does not take the poll down");
        {
            const auto status = parseTaskStatus (
                R"({"data":[{"status":1,"result":"not json"}],"code":200})", "http://127.0.0.1:8001");

            expect (status.ok, "a bad result field broke the whole status read");
            expect (status.state == TaskStatus::State::completed);
            expectEquals (status.audioUrls.size(), 0);
        }

        beginTest ("query posts the task id in the list the server expects");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            const auto status = queryTask (server.getBaseUrl(), "", "task-xyz");

            expect (status.ok, status.errorMessage);
            expectEquals (server.getLastPath(), juce::String ("/query_result"));

            const auto sent = juce::JSON::parse (server.getLastBody());
            auto* ids = sent.getProperty ("task_id_list", juce::var()).getArray();
            expect (ids != nullptr, "task_id_list was not an array: " + server.getLastBody());
            expectEquals (ids->size(), 1);
            expectEquals ((*ids)[0].toString(), juce::String ("task-xyz"));
        }

        beginTest ("download writes the file and reports nothing wrong");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/v1/audio", "RIFF....fake wav payload....");

            const auto destination = juce::File::getSpecialLocation (juce::File::tempDirectory)
                                         .getChildFile ("acemusic-download-"
                                                        + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)))
                                         .getChildFile ("clip.wav");

            const auto error = downloadAudio (server.getBaseUrl() + "/v1/audio?path=clip.wav", "", destination);

            expect (error.isEmpty(), error);
            expect (destination.existsAsFile(), "no file was written");
            expectEquals (destination.loadFileAsString(), juce::String ("RIFF....fake wav payload...."));

            destination.getParentDirectory().deleteRecursively();
        }

        beginTest ("download leaves no partial file behind when the server sends nothing");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/v1/audio", "");

            const auto destination = juce::File::getSpecialLocation (juce::File::tempDirectory)
                                         .getChildFile ("acemusic-empty-"
                                                        + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)))
                                         .getChildFile ("clip.wav");

            const auto error = downloadAudio (server.getBaseUrl() + "/v1/audio?path=clip.wav", "", destination);

            expect (error.isNotEmpty(), "an empty download was reported as success");
            expect (! destination.existsAsFile(), "left an empty file that looks like a usable clip");
            expect (! destination.getSiblingFile (destination.getFileName() + ".part").existsAsFile(),
                    "left a .part file behind");

            destination.getParentDirectory().deleteRecursively();
        }

        beginTest ("a cancelled download writes nothing");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/v1/audio", "some audio bytes");

            const auto destination = juce::File::getSpecialLocation (juce::File::tempDirectory)
                                         .getChildFile ("acemusic-cancel-"
                                                        + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)))
                                         .getChildFile ("clip.wav");

            const auto error = downloadAudio (server.getBaseUrl() + "/v1/audio?path=clip.wav", "",
                                              destination, [] { return true; });

            expect (error.isEmpty(), "a cancellation was reported as an error: " + error);
            expect (! destination.existsAsFile(), "wrote a file despite being cancelled");

            destination.getParentDirectory().deleteRecursively();
        }

        beginTest ("submit and query honour cancellation before touching the network");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            const auto submitted = submitGeneration (server.getBaseUrl(), "", "{}", [] { return true; });
            expect (submitted.cancelled, "submit did not report cancellation");
            expect (! submitted.ok);

            const auto queried = queryTask (server.getBaseUrl(), "", "id", [] { return true; });
            expect (queried.cancelled, "query did not report cancellation");

            expectEquals (server.getRequestCount(), 0, "contacted the server despite being cancelled");
        }
    }
};

static GenerationClientTests generationClientTests;

} // namespace acemusic
