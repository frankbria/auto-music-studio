/*
  Platform-routed generation for custom voices (#396).

  A voice model lives on the platform and its LoRA adapter is loaded on the ACE-Step host
  by the platform's own worker. So when a voice is chosen the plugin must not touch the
  adapter itself — it hands the whole generation to the platform and lets the single
  existing owner of that state run it. With no voice chosen nothing changes: generation
  still goes straight to the local server, free and offline.

  Served by a real loopback stub rather than a mocked client, for the reason
  StubAceStepServer.h records: a mock would pass even with the transport broken.
*/

#include <juce_gui_basics/juce_gui_basics.h>

#include "BackgroundTaskQueue.h"
#include "ClipCache.h"
#include "ConnectionManager.h"
#include "GenerationManager.h"
#include "GenerationRequest.h"
#include "PlatformClient.h"
#include "PluginEditor.h"
#include "PluginProcessor.h"
#include "StubAceStepServer.h"

namespace
{
/** Runs the message loop until `predicate` holds, as every other panel/manager suite here
    does — the manager posts its state back through BackgroundTaskQueue::callOnMessageThread,
    so nothing is observable without pumping. */
bool pumpUntil (std::function<bool()> predicate, int timeoutMs)
{
    const auto deadline = juce::Time::getMillisecondCounter() + (juce::uint32) timeoutMs;

    while (juce::Time::getMillisecondCounter() < deadline)
    {
        if (predicate())
            return true;

        juce::MessageManager::getInstance()->runDispatchLoopUntil (10);
    }

    return predicate();
}

/** A throwaway settings file with the clip cache pointed at a temp directory.

    Emphatically not the default cache location: an earlier suite deleted the developer's
    real generations by recursing the default directory. */
struct ScopedClipCleanup
{
    ScopedClipCleanup()
    {
        root = juce::File::getSpecialLocation (juce::File::tempDirectory)
                   .getChildFile ("acemusic-voiceclips-"
                                  + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
        root.createDirectory();

        juce::PropertiesFile::Options options;
        options.applicationName = "VoiceTest";
        options.filenameSuffix  = ".settings";
        options.storageFormat   = juce::PropertiesFile::storeAsXML;

        properties = std::make_unique<juce::PropertiesFile> (root.getChildFile ("VoiceTest.settings"), options);
        properties->setValue (acemusic::ClipCache::cachePathKey, root.getChildFile ("clips").getFullPathName());
        properties->saveIfNeeded();
    }

    ~ScopedClipCleanup()
    {
        properties.reset();
        root.deleteRecursively();
    }

    juce::File root;
    std::unique_ptr<juce::PropertiesFile> properties;
};

/** Writes a PNG of `component` when ACEMUSIC_DEMO_DIR is set, else does nothing.

    The demo needs pictures of the real editor in the states the acceptance criteria
    describe — and these tests already build exactly those states. Driving the standalone
    app instead would mean clicking Connect, and there is no xdotool on this machine.
    Snapshotting the same component tree the assertions run against is the more honest
    evidence anyway: it cannot drift from what is tested. */
void captureIfRequested (juce::Component& component, const juce::String& name)
{
    const auto dir = juce::SystemStats::getEnvironmentVariable ("ACEMUSIC_DEMO_DIR", {});

    if (dir.isEmpty())
        return;

    const auto image = component.createComponentSnapshot (component.getLocalBounds(), true);
    const auto file = juce::File (dir).getChildFile (name + ".png");
    file.deleteFile();

    if (auto stream = file.createOutputStream())
        juce::PNGImageFormat().writeImageToStream (image, *stream);
}

juce::String voiceModelsBody()
{
    // The platform returns a bare array, newest first, with mixed statuses.
    return R"([
        {"id": "vm-ready", "name": "My Voice", "status": "ready", "reference_count": 6},
        {"id": "vm-training", "name": "Still Training", "status": "training", "reference_count": 3},
        {"id": "vm-failed", "name": "Broken", "status": "failed", "reference_count": 1}
    ])";
}
}

class VoiceGenerationTests final : public juce::UnitTest
{
public:
    VoiceGenerationTests() : juce::UnitTest ("VoiceGeneration", "acemusic") {}

    void runTest() override
    {
        using namespace acemusic;

        beginTest ("AC: an authenticated session lists the user's voice models");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/voice-models", voiceModelsBody());

            const auto result = Platform::listVoiceModels (server.getBaseUrl(), "token", nullptr, 5000);

            expect (result.ok, result.errorMessage);
            expectEquals (result.voiceModels.size(), 3);
            expectEquals (result.voiceModels[0].id, juce::String ("vm-ready"));
            expectEquals (result.voiceModels[0].name, juce::String ("My Voice"));
            expectEquals (result.voiceModels[0].status, juce::String ("ready"));
            // The bearer token actually went out — the endpoint is user-scoped.
            expect (server.getLastRequest().contains ("Authorization: Bearer token"));
        }

        beginTest ("AC: only ready models are offered");
        {
            // Filtering is the client's job: a model still training cannot generate, and
            // offering it would produce a 409 the musician did not ask for.
            juce::Array<Platform::VoiceModel> models;
            models.add ({ "a", "Ready", "ready" });
            models.add ({ "b", "Training", "training" });
            models.add ({ "c", "Failed", "failed" });
            models.add ({ "d", "Queued", "queued" });

            const auto ready = Platform::readyVoiceModels (models);

            expectEquals (ready.size(), 1);
            expectEquals (ready[0].id, juce::String ("a"));
        }

        beginTest ("a voice list that is not a list fails rather than showing nothing");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/voice-models", R"({"detail": "Not authenticated"})");

            const auto result = Platform::listVoiceModels (server.getBaseUrl(), "token", nullptr, 5000);

            expect (! result.ok);
            expect (result.errorMessage.isNotEmpty());
        }

        beginTest ("the platform payload is not the ACE-Step payload");
        {
            // POST /api/v1/generate rejects unknown keys outright (extra="forbid"), so the
            // two serialisers cannot be shared. This pins the shape the platform accepts.
            GenerationRequest request;
            request.prompt = "a calm piano ballad";
            request.voiceModelId = "vm-ready";
            request.durationSeconds = 45.0;
            request.bpm = 120;

            const auto payload = juce::JSON::parse (request.toPlatformPayloadJson());

            expectEquals (payload.getProperty ("prompt", {}).toString(), juce::String ("a calm piano ballad"));
            expectEquals (payload.getProperty ("voice_model_id", {}).toString(), juce::String ("vm-ready"));
            expect (payload.hasProperty ("duration"));
            // ACE-Step-only keys must not leak into a body that forbids extras.
            expect (! payload.hasProperty ("audio_duration"));
            expect (! payload.hasProperty ("task_type"));
        }

        beginTest ("an omitted voice leaves voice_model_id out entirely");
        {
            // Sending null would be a different request than sending nothing, and the
            // no-voice path is meant to be untouched.
            GenerationRequest request;
            request.prompt = "a calm piano ballad";

            const auto payload = juce::JSON::parse (request.toPlatformPayloadJson());

            expect (! payload.hasProperty ("voice_model_id"));
        }

        beginTest ("AC: submitting returns the platform's job id");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/generate",
                                   R"({"job_id": "job-123", "status": "queued", "estimated_time_seconds": 60})");

            GenerationRequest request;
            request.prompt = "a calm piano ballad";
            request.voiceModelId = "vm-ready";

            const auto result = Platform::submitGeneration (server.getBaseUrl(), "token",
                                                            request.toPlatformPayloadJson(), nullptr, 5000);

            expect (result.ok, result.errorMessage);
            expectEquals (result.jobId, juce::String ("job-123"));
            expect (server.getBodyFor ("/api/v1/generate").contains ("vm-ready"));
        }

        beginTest ("job status maps onto the states the manager already has");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/jobs/job-123/status",
                                   R"({"job_id": "job-123", "status": "completed",
                                       "clip_ids": ["clip-a", "clip-b"],
                                       "audio_urls": ["/data/storage/a.wav", "/data/storage/b.wav"]})");

            const auto result = Platform::getJobStatus (server.getBaseUrl(), "token", "job-123", nullptr, 5000);

            expect (result.ok, result.errorMessage);
            expect (result.jobComplete);
            expect (! result.jobFailed);
            expectEquals (result.clipIds.size(), 2);
            expectEquals (result.clipIds[0], juce::String ("clip-a"));
        }

        beginTest ("a failed job carries the platform's own reason");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/jobs/job-9/status",
                                   R"({"job_id": "job-9", "status": "failed", "error": "ACE-Step base URL is not configured"})");

            const auto result = Platform::getJobStatus (server.getBaseUrl(), "token", "job-9", nullptr, 5000);

            expect (result.ok, result.errorMessage);
            expect (result.jobFailed);
            expect (result.errorMessage.contains ("ACE-Step base URL"));
        }

        beginTest ("a queued job is neither complete nor failed");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setResponseFor ("/api/v1/jobs/job-1/status",
                                   R"({"job_id": "job-1", "status": "queued", "progress": "waiting"})");

            const auto result = Platform::getJobStatus (server.getBaseUrl(), "token", "job-1", nullptr, 5000);

            expect (result.ok, result.errorMessage);
            expect (! result.jobComplete);
            expect (! result.jobFailed);
        }

        beginTest ("the tier refusal reaches the musician instead of a bare status code");
        {
            // A free account naming a voice gets 403 from the platform. "API key rejected"
            // would be a lie about what went wrong.
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 403 Forbidden");
            server.setResponseFor ("/api/v1/generate",
                                   R"({"detail": {"error": "upgrade_required", "feature": "Custom voices",
                                       "message": "Custom voices are a Pro feature."}})");

            GenerationRequest request;
            request.prompt = "a calm piano ballad";
            request.voiceModelId = "vm-ready";

            const auto result = Platform::submitGeneration (server.getBaseUrl(), "token",
                                                            request.toPlatformPayloadJson(), nullptr, 5000);

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("Pro"), "got: " + result.errorMessage);
        }

        beginTest ("AC: a voiced run goes to the platform, an unvoiced one does not");
        {
            // The whole point of the hybrid. Both runs are driven through the real
            // GenerationManager against one stub serving both APIs, and the assertion is
            // which endpoints each one actually touched.
            ScopedClipCleanup cleanup;
            test::StubAceStepServer server;
            expect (server.start() != 0);

            server.setResponseFor ("/v1/stats", R"({"data":{"models":[{"name":"ace-step-1.5"}]},"code":200})");
            server.setResponseFor ("/release_task", R"({"data":{"task_id":"t-1"},"code":200})");
            server.setResponseFor ("/query_result",
                                   R"({"data":[{"status":2,"result":"[{\"file\": \"/v1/audio?path=a.wav\"}]"}],"code":200})");
            server.setResponseFor ("/v1/audio", "RIFFfake-wave-bytes-for-the-test");

            cleanup.properties->setValue (acemusic::Platform::urlKey, server.getBaseUrl());
            cleanup.properties->setValue (acemusic::Platform::apiKeyKey, "token");
            cleanup.properties->saveIfNeeded();

            BackgroundTaskQueue queue;
            ConnectionManager connection (queue, nullptr);
            GenerationManager generation (queue, connection, cleanup.properties.get());

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            connection.setSettings (settings);
            connection.testConnection();
            expect (pumpUntil ([&] { return connection.getStatus() == ConnectionManager::Status::Connected; }, 10000),
                    "never connected: " + connection.getStatusMessage());

            // 1. No voice: the local path, untouched.
            GenerationRequest plain;
            plain.prompt = "slow shoegaze wall of guitars";
            generation.start (plain);
            expect (pumpUntil ([&] { return ! generation.isBusy(); }, 20000),
                    "unvoiced run never finished: " + generation.getStatusMessage());

            expect (server.getRequestCountFor ("/release_task") > 0, "the local server was not used");
            expectEquals (server.getRequestCountFor ("/api/v1/generate"), 0);

            // 2. A voice: the platform path.
            server.setResponseFor ("/api/v1/generate", R"({"job_id":"job-7","status":"queued"})");
            server.setResponseFor ("/api/v1/jobs/job-7/status",
                                   R"({"job_id":"job-7","status":"completed","clip_ids":["clip-a"]})");
            server.setResponseFor ("/api/v1/clips/clip-a/audio", "RIFFfake-wave-bytes-for-the-test");

            const auto localCallsBefore = server.getRequestCountFor ("/release_task");

            GenerationRequest voiced;
            voiced.prompt = "slow shoegaze wall of guitars";
            voiced.voiceModelId = "vm-ready";
            generation.start (voiced);
            expect (pumpUntil ([&] { return ! generation.isBusy(); }, 20000),
                    "voiced run never finished: " + generation.getStatusMessage());

            expect (server.getRequestCountFor ("/api/v1/generate") > 0,
                    "the platform was not used: " + generation.getStatusMessage());
            // AC: only one component owns the LoRA state. The plugin must not have gone
            // near the local generation endpoint for a voiced run.
            expectEquals (server.getRequestCountFor ("/release_task"), localCallsBefore);
            expectEquals (generation.getClips().size(), 1);
        }

        beginTest ("AC: signed out hides the selector rather than showing an empty list");
        {
            // A musician who has not connected has no voices and cannot get any without
            // connecting, so a control reading "None" is a question the plugin cannot
            // answer. It is not shown at all.
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            expect (! panel.getVoiceSelector().isVisible(), "the selector showed while signed out");
            expect (panel.getSelectedVoiceModelId().isEmpty());
            captureIfRequested (editor, "us396-signed-out");
            // And an unvoiced request is exactly what it always was.
            expect (panel.buildRequest().voiceModelId.isEmpty());
        }

        beginTest ("AC: connecting offers the ready voices, and only those");
        {
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> models;
            models.add ({ "vm-ready", "My Voice", "ready" });
            models.add ({ "vm-training", "Still Training", "training" });
            panel.setVoiceModels (models);

            expect (panel.getVoiceSelector().isVisible());
            // "None" plus the one ready model — the trainee is not offered.
            expectEquals (panel.getVoiceSelector().getNumItems(), 2);
            expectEquals (panel.getVoiceSelector().getItemText (1), juce::String ("My Voice"));

            // AC: selecting one puts it on the request, which is what routes the run.
            panel.getVoiceSelector().setSelectedId (2, juce::sendNotificationSync);
            expectEquals (panel.getSelectedVoiceModelId(), juce::String ("vm-ready"));
            expectEquals (panel.buildRequest().voiceModelId, juce::String ("vm-ready"));

            captureIfRequested (editor, "us396-voice-selected");

            // AC: back to None and the request is unvoiced again.
            panel.getVoiceSelector().setSelectedId (1, juce::sendNotificationSync);
            expect (panel.buildRequest().voiceModelId.isEmpty());
        }

        beginTest ("signing out takes the selector away again");
        {
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> models;
            models.add ({ "vm-ready", "My Voice", "ready" });
            panel.setVoiceModels (models);
            panel.getVoiceSelector().setSelectedId (2, juce::sendNotificationSync);

            panel.setVoiceModels ({});

            expect (! panel.getVoiceSelector().isVisible());
            // And crucially the stale choice does not linger on the request.
            expect (panel.buildRequest().voiceModelId.isEmpty());
        }

        beginTest ("a voice deleted on the web does not stay selected");
        {
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> before;
            before.add ({ "vm-a", "Voice A", "ready" });
            before.add ({ "vm-b", "Voice B", "ready" });
            panel.setVoiceModels (before);
            panel.getVoiceSelector().setSelectedId (3, juce::sendNotificationSync);
            expectEquals (panel.getSelectedVoiceModelId(), juce::String ("vm-b"));

            juce::Array<Platform::VoiceModel> after;
            after.add ({ "vm-a", "Voice A", "ready" });
            panel.setVoiceModels (after);

            // Falls back to None rather than silently sliding onto Voice A.
            expect (panel.getSelectedVoiceModelId().isEmpty(), "kept a deleted voice selected");
        }

        beginTest ("a surviving voice keeps its selection across a refresh");
        {
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> models;
            models.add ({ "vm-a", "Voice A", "ready" });
            models.add ({ "vm-b", "Voice B", "ready" });
            panel.setVoiceModels (models);
            panel.getVoiceSelector().setSelectedId (3, juce::sendNotificationSync);

            // A refresh that returns the same list in a different order must not move the
            // musician's choice onto a different voice.
            juce::Array<Platform::VoiceModel> reordered;
            reordered.add ({ "vm-b", "Voice B", "ready" });
            reordered.add ({ "vm-a", "Voice A", "ready" });
            panel.setVoiceModels (reordered);

            expectEquals (panel.getSelectedVoiceModelId(), juce::String ("vm-b"));
        }

        beginTest ("a voice outside Text to Music is refused, not silently flattened");
        {
            // The platform cannot reach this machine's source audio, so a voiced Cover /
            // Complete / Repaint / Lego would arrive there as a plain text-to-music
            // request with the source dropped — a generation the musician did not ask
            // for. Raised in review: the code comment said "only text-to-music is routed"
            // and nothing enforced it.
            GenerationRequest request;
            request.prompt = "a calm piano ballad";
            request.voiceModelId = "vm-ready";
            request.sourceAudioPath = "/tmp/source.wav";
            request.mode = GenerationRequest::Mode::cover;

            const auto problem = request.findProblem();

            expect (problem.isNotEmpty(), "a voiced cover was accepted");
            expect (problem.containsIgnoreCase ("Text to Music"), "unhelpful message: " + problem);

            // The same request without the voice is fine, and unchanged.
            request.voiceModelId = {};
            expect (request.findProblem().isEmpty());
        }

        beginTest ("switching away from Text to Music clears the voice");
        {
            // Prevention as well as refusal: a selection made in Text to Music must not
            // survive a mode switch and then block Generate with a message about a
            // control the musician can no longer see.
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> models;
            models.add ({ "vm-ready", "My Voice", "ready" });
            panel.setVoiceModels (models);
            panel.getVoiceSelector().setSelectedId (2, juce::sendNotificationSync);
            expectEquals (panel.getSelectedVoiceModelId(), juce::String ("vm-ready"));

            const auto coverIndex = GenerationRequest::allModes().indexOf (GenerationRequest::Mode::cover);
            panel.getModeSelector().setSelectedId (coverIndex + 1, juce::sendNotificationSync);

            expect (! panel.getVoiceSelector().isVisible(), "the selector stayed visible outside Text to Music");
            expect (panel.getSelectedVoiceModelId().isEmpty(), "the voice survived the mode switch");
            expect (panel.buildRequest().voiceModelId.isEmpty());
        }

        beginTest ("a voiced run does not need the local ACE-Step server");
        {
            // The platform runs it. Refusing because the *local* server is offline would
            // block a generation that would have worked — raised in review.
            ScopedClipCleanup cleanup;
            cleanup.properties->setValue (acemusic::Platform::urlKey, "http://127.0.0.1:9");
            cleanup.properties->saveIfNeeded();

            BackgroundTaskQueue queue;
            ConnectionManager connection (queue, nullptr);   // never connected
            GenerationManager generation (queue, connection, cleanup.properties.get());

            GenerationRequest voiced;
            voiced.prompt = "a calm piano ballad";
            voiced.voiceModelId = "vm-ready";

            expect (generation.findStartProblem (voiced).isEmpty(),
                    "voiced run refused: " + generation.findStartProblem (voiced));

            // An unvoiced run still needs it, exactly as before.
            GenerationRequest plain;
            plain.prompt = "a calm piano ballad";
            expect (generation.findStartProblem (plain).containsIgnoreCase ("ACE-Step"));
        }

        beginTest ("a voiced run with no platform configured says which connection is missing");
        {
            ScopedClipCleanup cleanup;   // no platform URL set

            BackgroundTaskQueue queue;
            ConnectionManager connection (queue, nullptr);
            GenerationManager generation (queue, connection, cleanup.properties.get());

            GenerationRequest voiced;
            voiced.prompt = "a calm piano ballad";
            voiced.voiceModelId = "vm-ready";

            const auto problem = generation.findStartProblem (voiced);

            expect (problem.containsIgnoreCase ("platform"), "unhelpful message: " + problem);
        }

        beginTest ("the selector fits at the editor's minimum size");
        {
            // It shares the Lego row rather than taking one of its own, because the
            // editor's minimum height is already tight and every prior story's comment in
            // PluginEditor::resized warns about squeezing the readouts.
            //
            // Sharing is safe because the two are now mutually exclusive: a voice is only
            // offered in Text to Music, where the Lego controls are hidden. That was not
            // true when this test was written — it asserted the two did not overlap, and
            // the review fix for voiced non-text modes removed the contention entirely.
            ScopedClipCleanup cleanup;
            PluginProcessor processor (std::move (cleanup.properties), false);
            PluginEditor editor (processor);
            editor.setSize (560, 990);   // the configured minimum

            auto& panel = editor.getGenerationPanel();

            juce::Array<Platform::VoiceModel> models;
            models.add ({ "vm-ready", "A Very Long Voice Model Name Indeed", "ready" });
            panel.setVoiceModels (models);

            expect (panel.getVoiceSelector().isVisible(), "not offered in Text to Music");
            expect (panel.getVoiceSelector().getWidth() > 0, "the voice selector collapsed");
            expect (panel.getVoiceLabel().getWidth() > 0, "the caption collapsed");
            expect (editor.getLocalBounds().contains (panel.getBounds()), "the panel escaped the editor");
            expect (! panel.getLegoTrackSelector().isVisible(), "lego and voice were both visible");
            captureIfRequested (editor, "us396-minimum-size");
        }

        beginTest ("running out of credits says so, with the numbers");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 402 Payment Required");
            server.setResponseFor ("/api/v1/generate",
                                   R"({"detail": {"error": "insufficient_credits", "balance": 0.5, "required": 1.0,
                                       "message": "This action needs 1.0 credits; balance is 0.5."}})");

            GenerationRequest request;
            request.prompt = "a calm piano ballad";
            request.voiceModelId = "vm-ready";

            const auto result = Platform::submitGeneration (server.getBaseUrl(), "token",
                                                            request.toPlatformPayloadJson(), nullptr, 5000);

            expect (! result.ok);
            expect (result.errorMessage.containsIgnoreCase ("credits"), "got: " + result.errorMessage);
        }
    }
};

static VoiceGenerationTests voiceGenerationTests;
