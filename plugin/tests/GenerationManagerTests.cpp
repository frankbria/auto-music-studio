#include "ClipCache.h"
#include "GenerationManager.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

class GenerationManagerTests final : public juce::UnitTest
{
public:
    GenerationManagerTests()
        : juce::UnitTest ("GenerationManager", "acemusic")
    {
    }

    bool pumpUntil (std::function<bool()> predicate, int timeoutMs = 20000)
    {
        auto* mm = juce::MessageManager::getInstance();
        const auto start = juce::Time::getMillisecondCounter();

        while (! predicate())
        {
            if ((juce::uint32) (juce::Time::getMillisecondCounter() - start) >= (juce::uint32) timeoutMs)
                return false;

            mm->runDispatchLoopUntil (10);
        }

        return true;
    }

    /** A stub wired for the whole submit → poll → download sequence, plus a connected
        ConnectionManager pointed at it. */
    struct Harness
    {
        Harness()
            : manager (queue, nullptr),
              generation (queue, manager)
        {
        }

        /** Points the connection at the stub and gets it to Connected. */
        bool connect (juce::UnitTest& test, std::function<bool(std::function<bool()>)> pump)
        {
            server.setResponseFor ("/v1/stats",
                                   R"({"data":{"models":[{"name":"ace-step-1.5"}]},"code":200})");
            server.setResponseFor ("/release_task", R"({"data":{"task_id":"t-1"},"code":200})");

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);
            manager.testConnection();

            const auto connected = pump ([this] { return manager.getStatus() == ConnectionManager::Status::Connected; });
            test.expect (connected, "the harness never connected: " + manager.getStatusMessage());
            return connected;
        }

        static GenerationRequest request()
        {
            GenerationRequest r;
            r.prompt = "slow shoegaze wall of guitars";
            return r;
        }

        test::StubAceStepServer server;
        BackgroundTaskQueue queue;
        ConnectionManager manager;
        GenerationManager generation;
    };

    /** Cleans up whatever the manager wrote under its clip directory. */
    struct ScopedClipCleanup
    {
        ~ScopedClipCleanup()  { ClipCache::getDefaultDirectory().deleteRecursively(); }
    };

    void runTest() override
    {
        using State = GenerationManager::State;

        beginTest ("starts idle and refuses to run without a connection");
        {
            BackgroundTaskQueue queue;
            ConnectionManager connection (queue, nullptr);
            GenerationManager generation (queue, connection);

            expect (generation.getState() == State::idle);
            expect (! generation.isBusy());
            expectEquals (generation.getClips().size(), 0);
            expectEquals (generation.getElapsedSeconds(), 0);

            // AC: generation is unavailable while the connection is not green.
            const auto problem = generation.findStartProblem (Harness::request());
            expect (problem.isNotEmpty(), "allowed a generation with no connection");
            expect (problem.containsIgnoreCase ("connect"), problem);

            generation.start (Harness::request());
            expect (generation.getState() == State::idle, "started anyway");
            expectEquals (queue.getNumPending(), 0);
        }

        beginTest ("an invalid request is refused with the request's own reason");
        {
            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            GenerationRequest blank;   // no prompt
            const auto problem = harness.generation.findStartProblem (blank);
            expect (problem.containsIgnoreCase ("prompt"), problem);

            harness.generation.start (blank);
            expect (harness.generation.getState() == State::idle);
        }

        beginTest ("AC: a prompt produces 2 clips, through every progress state");
        {
            ScopedClipCleanup cleanup;

            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            // First poll pending, then completed with two files.
            harness.server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");
            harness.server.setResponseFor ("/v1/audio", "RIFF fake wav bytes");

            juce::Array<State> seen;
            struct Recorder final : juce::ChangeListener
            {
                Recorder (GenerationManager& g, juce::Array<State>& out) : gen (g), states (out) {}
                void changeListenerCallback (juce::ChangeBroadcaster*) override
                {
                    if (states.isEmpty() || states.getLast() != gen.getState())
                        states.add (gen.getState());
                }
                GenerationManager& gen;
                juce::Array<State>& states;
            };

            Recorder recorder (harness.generation, seen);
            harness.generation.addChangeListener (&recorder);

            harness.generation.start (Harness::request());

            // start() must not block the caller — the DAW's message thread is here.
            expect (harness.generation.getState() == State::submitting, "did not enter submitting");
            expect (harness.generation.isBusy());

            // Let it get past submit, then hand it a completed task.
            expect (pumpUntil ([&] { return harness.server.getRequestCountFor ("/query_result") >= 1; }),
                    "never polled the server");

            harness.server.setResponseFor ("/query_result",
                R"({"data":[{"status":1,"result":"[{\"file\":\"/v1/audio?path=a.wav\"},{\"file\":\"/v1/audio?path=b.wav\"}]"}],"code":200})");

            expect (pumpUntil ([&] { return harness.generation.getState() == State::complete
                                         || harness.generation.getState() == State::failed; }, 30000),
                    "generation never finished, stuck at: " + harness.generation.getStatusMessage());

            expect (harness.generation.getState() == State::complete,
                    "expected complete, got \"" + harness.generation.getStatusMessage() + "\"");

            // AC: 2 clips.
            expect (pumpUntil ([&] { return harness.generation.getClips().size() == 2; }),
                    "expected 2 clips, got " + juce::String (harness.generation.getClips().size()));

            for (const auto& clip : harness.generation.getClips())
                expect (clip.existsAsFile(), "clip was not written: " + clip.getFullPathName());

            // AC: progress moved through the real states rather than jumping.
            expect (seen.contains (State::submitting), "never reported submitting");
            expect (seen.contains (State::queued), "never reported queued");
            expect (seen.contains (State::downloading), "never reported downloading");
            expect (seen.contains (State::complete), "never reported complete");

            harness.generation.removeChangeListener (&recorder);
        }

        beginTest ("AC: every parameter reaches the API, verified from the request body");
        {
            ScopedClipCleanup cleanup;

            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            harness.server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            auto request = Harness::request();
            request.lyrics          = "[Verse]\nline one";
            request.vocalLanguage   = "Portuguese";
            request.bpm             = 141;
            request.key             = "D minor";
            request.durationSeconds = 45;
            request.seed            = 77;
            request.quality         = GenerationRequest::Quality::turbo;

            harness.generation.start (request);

            expect (pumpUntil ([&] { return harness.server.getRequestCountFor ("/release_task") >= 1; }),
                    "never submitted");

            // Assert on the body captured for /release_task specifically — by now the
            // most recent request is a poll.
            const auto sent = juce::JSON::parse (harness.server.getBodyFor ("/release_task"));
            expect (sent.getDynamicObject() != nullptr,
                    "submit body was not JSON: " + harness.server.getBodyFor ("/release_task"));

            expectEquals (sent.getProperty ("prompt", juce::var()).toString(), request.prompt);
            expectEquals (sent.getProperty ("lyrics", juce::var()).toString(), request.lyrics);
            expectEquals (sent.getProperty ("vocal_language", juce::var()).toString(), juce::String ("Portuguese"));
            expectEquals ((int) sent.getProperty ("bpm", juce::var()), 141);
            expectEquals (sent.getProperty ("key", juce::var()).toString(), juce::String ("D minor"));
            expectEquals ((int) sent.getProperty ("audio_duration", juce::var()), 45);
            expectEquals ((juce::int64) sent.getProperty ("seed", juce::var()), (juce::int64) 77);
            expectEquals ((int) sent.getProperty ("inference_steps", juce::var()), 8, "Turbo should be 8 steps");
            expectEquals ((int) sent.getProperty ("batch_size", juce::var()), 2);

            // The model comes from the connection panel, not the request.
            expectEquals (sent.getProperty ("model", juce::var()).toString(), juce::String ("ace-step-1.5"));

            harness.generation.cancel();
            expect (pumpUntil ([&] { return ! harness.generation.isBusy(); }, 30000), "cancel never settled");
        }

        beginTest ("a failed task surfaces the server's own error");
        {
            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            harness.server.setResponseFor ("/query_result",
                R"({"data":[{"status":2,"error":"CUDA out of memory"}],"code":200})");

            harness.generation.start (Harness::request());

            expect (pumpUntil ([&] { return harness.generation.getState() == State::failed; }, 30000),
                    "never failed, stuck at: " + harness.generation.getStatusMessage());
            expectEquals (harness.generation.getStatusMessage(), juce::String ("CUDA out of memory"));
            expectEquals (harness.generation.getClips().size(), 0);
        }

        beginTest ("a completed task with no audio is a failure, not a silent success");
        {
            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            harness.server.setResponseFor ("/query_result", R"({"data":[{"status":1,"result":"[]"}],"code":200})");

            harness.generation.start (Harness::request());

            expect (pumpUntil ([&] { return harness.generation.getState() == State::failed; }, 30000),
                    "reported success with no audio");
            expect (harness.generation.getStatusMessage().containsIgnoreCase ("no audio"),
                    harness.generation.getStatusMessage());
        }

        beginTest ("cancel stops a run in flight");
        {
            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            // Stays pending forever unless cancelled.
            harness.server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            harness.generation.start (Harness::request());
            expect (pumpUntil ([&] { return harness.server.getRequestCountFor ("/query_result") >= 1; }),
                    "never started polling");

            harness.generation.cancel();

            expect (pumpUntil ([&] { return harness.generation.getState() == State::cancelled; }, 30000),
                    "never reached cancelled, stuck at: " + harness.generation.getStatusMessage());
            expect (! harness.generation.isBusy());
            expectEquals (harness.generation.getClips().size(), 0);
        }

        beginTest ("a second start while one is running is refused");
        {
            Harness harness;
            expect (harness.server.start() != 0);
            if (! harness.connect (*this, [this] (auto p) { return pumpUntil (p); }))
                return;

            harness.server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            harness.generation.start (Harness::request());
            expect (harness.generation.isBusy());

            const auto submitsBefore = harness.server.getRequestCountFor ("/release_task");
            harness.generation.start (Harness::request());

            expect (harness.generation.findStartProblem (Harness::request()).containsIgnoreCase ("already"),
                    "did not report that one is already running");

            harness.generation.cancel();
            expect (pumpUntil ([&] { return ! harness.generation.isBusy(); }, 30000), "cancel never settled");

            expectEquals (harness.server.getRequestCountFor ("/release_task"), submitsBefore,
                          "a second run was submitted while one was in flight");
        }

        beginTest ("a run outliving its manager is a no-op, not a crash");
        {
            // The queue is declared first so it outlives the manager, exactly as
            // PluginProcessor orders them.
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/v1/stats", R"({"data":{"models":[{"name":"m"}]},"code":200})");
            server.setResponseFor ("/release_task", R"({"data":{"task_id":"t"},"code":200})");
            server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            BackgroundTaskQueue queue;

            {
                ConnectionManager connection (queue, nullptr);
                GenerationManager generation (queue, connection);

                ConnectionSettings settings;
                settings.serverUrl = server.getBaseUrl();
                connection.setSettings (settings);
                connection.testConnection();
                expect (pumpUntil ([&] { return connection.getStatus() == ConnectionManager::Status::Connected; }));

                generation.start (Harness::request());
                expect (pumpUntil ([&] { return server.getRequestCountFor ("/release_task") >= 1; }),
                        "never submitted");
                // both managers die here with the run still polling
            }

            expect (queue.waitForAll (30000), "the run did not stop after its manager went away");

            auto* mm = juce::MessageManager::getInstance();
            for (int i = 0; i < 25; ++i)
                mm->runDispatchLoopUntil (10);

            expect (true, "survived a run outliving its manager");
        }
    }
};

static GenerationManagerTests generationManagerTests;

} // namespace acemusic
