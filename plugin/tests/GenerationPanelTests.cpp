#include "ClipCache.h"
#include "PluginEditor.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

/** Drives the real widgets through the real editor. Needs a display — on a headless
    Linux box run under `xvfb-run -a`. */
class GenerationPanelTests final : public juce::UnitTest
{
public:
    GenerationPanelTests()
        : juce::UnitTest ("GenerationPanel", "acemusic")
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

    struct Harness
    {
        explicit Harness (std::unique_ptr<juce::PropertiesFile> settings = nullptr)
            : processor (std::move (settings), false),
              editor (processor)
        {
            editor.setSize (720, 640);
        }

        GenerationPanel& panel()          { return editor.getGenerationPanel(); }
        GenerationManager& generation()   { return processor.getGenerationManager(); }
        ConnectionManager& connection()   { return processor.getConnectionManager(); }

        PluginProcessor processor;
        PluginEditor editor;
    };

    /** Throwaway settings pointing the clip cache somewhere disposable — never the
        user's real cache, which these tests used to delete recursively. */
    struct ScopedClipCleanup
    {
        ScopedClipCleanup()
        {
            root = juce::File::getSpecialLocation (juce::File::tempDirectory)
                       .getChildFile ("acemusic-panelclips-"
                                      + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            root.createDirectory();

            juce::PropertiesFile::Options options;
            options.applicationName = "PanelGenTest";
            options.filenameSuffix  = ".settings";
            options.storageFormat   = juce::PropertiesFile::storeAsXML;

            properties = std::make_unique<juce::PropertiesFile> (root.getChildFile ("PanelGenTest.settings"),
                                                                  options);
            properties->setValue (ClipCache::cachePathKey,
                                  root.getChildFile ("clips").getFullPathName());
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

    /** Points the harness at `server` and waits for a green connection. */
    bool connect (Harness& harness, test::StubAceStepServer& server)
    {
        server.setResponseFor ("/v1/stats", R"({"data":{"models":[{"name":"ace-step-1.5"}]},"code":200})");
        server.setResponseFor ("/release_task", R"({"data":{"task_id":"t-1"},"code":200})");
        server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

        ConnectionSettings settings;
        settings.serverUrl = server.getBaseUrl();
        harness.connection().setSettings (settings);
        harness.connection().testConnection();

        return pumpUntil ([&] { return harness.connection().getStatus() == ConnectionManager::Status::Connected; });
    }

    void runTest() override
    {
        beginTest ("every control from the story is present with sane defaults");
        {
            Harness harness;
            auto& panel = harness.panel();

            expect (panel.getPromptEditor().isMultiLine(), "prompt is not a textarea");
            expect (panel.getLyricsEditor().isMultiLine(), "lyrics is not a textarea");

            // Lyrics are collapsed until asked for.
            expect (! panel.getLyricsToggle().getToggleState());
            expect (! panel.getLyricsEditor().isVisible(), "lyrics box is open by default");

            // "Auto"/"Any" are the first entry in each list, so nothing is sent unless
            // the user chooses.
            expectEquals (panel.getLanguageSelector().getSelectedId(), 1);
            expectEquals (panel.getKeySelector().getSelectedId(), 1);
            expectEquals (panel.getKeySelector().getItemText (0), juce::String ("Any"));

            expect (panel.getLanguageSelector().getNumItems() >= 51, "expected Auto + 50+ languages");
            expectEquals (panel.getQualitySelector().getNumItems(), 3);
            expectEquals (panel.getQualitySelector().getText(), juce::String ("Standard"));
            expectEquals (panel.getModeSelector().getNumItems(), 2);
            expectEquals (panel.getDurationEditor().getText(), juce::String ("60"));

            // BPM and seed are blank, meaning Auto/Random.
            expect (panel.getBpmEditor().getText().isEmpty());
            expect (panel.getSeedEditor().getText().isEmpty());
        }

        beginTest ("toggling lyrics shows the box");
        {
            Harness harness;
            auto& panel = harness.panel();

            panel.getLyricsToggle().setToggleState (true, juce::sendNotificationSync);
            expect (panel.getLyricsEditor().isVisible(), "lyrics box did not appear");

            panel.getLyricsToggle().setToggleState (false, juce::sendNotificationSync);
            expect (! panel.getLyricsEditor().isVisible(), "lyrics box did not collapse");
        }

        beginTest ("AC: Generate is unavailable until the connection is green");
        {
            Harness harness;
            auto& panel = harness.panel();

            panel.getPromptEditor().setText ("anything", true);

            expect (! panel.getGenerateButton().isEnabled(),
                    "Generate was live with no connection");
            expect (panel.getStatusLabel().getText().containsIgnoreCase ("connect"),
                    "did not say why: " + panel.getStatusLabel().getText());

            test::StubAceStepServer server;
            expect (server.start() != 0);
            expect (connect (harness, server), "never connected");

            expect (pumpUntil ([&] { return panel.getGenerateButton().isEnabled(); }),
                    "Generate stayed disabled after connecting");
        }

        beginTest ("Generate stays unavailable while the prompt is empty");
        {
            Harness harness;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            expect (connect (harness, server), "never connected");

            // Connected, but nothing to generate from.
            expect (! harness.panel().getGenerateButton().isEnabled(),
                    "Generate was live with an empty prompt");

            harness.panel().getPromptEditor().setText ("a prompt", true);
            expect (pumpUntil ([&] { return harness.panel().getGenerateButton().isEnabled(); }),
                    "Generate stayed disabled with a valid prompt");
        }

        beginTest ("the controls build the request the user described");
        {
            Harness harness;
            auto& panel = harness.panel();

            panel.getPromptEditor().setText ("hazy dub techno", true);
            panel.getLyricsToggle().setToggleState (true, juce::sendNotificationSync);
            panel.getLyricsEditor().setText ("[Verse]\nunder water", true);
            panel.getInstrumentalToggle().setToggleState (true, juce::sendNotificationSync);
            panel.getBpmEditor().setText ("122", true);
            panel.getDurationEditor().setText ("30", true);
            panel.getSeedEditor().setText ("99", true);
            panel.getQualitySelector().setSelectedId (1, juce::sendNotificationSync);   // Turbo
            panel.getKeySelector().setSelectedId (2, juce::sendNotificationSync);       // first real key
            panel.getLanguageSelector().setSelectedId (2, juce::sendNotificationSync);  // first real language

            const auto request = panel.buildRequest();

            expectEquals (request.prompt, juce::String ("hazy dub techno"));
            expectEquals (request.lyrics, juce::String ("[Verse]\nunder water"));
            expect (request.instrumental);
            expectEquals (request.bpm, 122);
            expectEquals (request.durationSeconds, 30);
            expectEquals ((int) request.seed, 99);
            expect (request.quality == GenerationRequest::Quality::turbo);
            expectEquals (request.key, panel.getKeySelector().getText());
            expectEquals (request.vocalLanguage, panel.getLanguageSelector().getText());
        }

        beginTest ("blank BPM and seed mean Auto and Random, not zero");
        {
            Harness harness;
            auto& panel = harness.panel();

            panel.getPromptEditor().setText ("something", true);

            const auto request = panel.buildRequest();
            expect (request.bpm < 0, "an empty BPM became " + juce::String (request.bpm));
            expect (request.seed < 0, "an empty seed became " + juce::String (request.seed));

            // And therefore neither reaches the payload.
            juce::var payload = request.toPayload();
            auto* object = payload.getDynamicObject();
            expect (object != nullptr);
            expect (! object->hasProperty ("bpm"));
            expect (! object->hasProperty ("seed"));
        }

        beginTest ("Auto language and Any key are omitted from the request");
        {
            Harness harness;
            auto& panel = harness.panel();
            panel.getPromptEditor().setText ("something", true);

            // Defaults: item 1 in both, which is Auto / Any.
            const auto request = panel.buildRequest();
            expect (request.vocalLanguage.isEmpty(), "Auto language leaked as " + request.vocalLanguage);
            expect (request.key.isEmpty(), "Any key leaked as " + request.key);
        }

        beginTest ("applyRequest round-trips through the controls");
        {
            Harness harness;

            GenerationRequest request;
            request.prompt          = "brass-led afrobeat";
            request.lyrics          = "[Chorus]\nrise";
            request.vocalLanguage   = "Yoruba";
            request.instrumental    = false;
            request.bpm             = 104;
            request.key             = "G minor";
            request.durationSeconds = 75;
            request.seed            = 12345;
            request.quality         = GenerationRequest::Quality::high;
            request.mode            = GenerationRequest::Mode::cover;

            harness.panel().applyRequest (request);
            const auto rebuilt = harness.panel().buildRequest();

            expectEquals (rebuilt.prompt, request.prompt);
            expectEquals (rebuilt.lyrics, request.lyrics);
            expectEquals (rebuilt.vocalLanguage, request.vocalLanguage);
            expectEquals (rebuilt.bpm, request.bpm);
            expectEquals (rebuilt.key, request.key);
            expectEquals (rebuilt.durationSeconds, request.durationSeconds);
            expectEquals ((int) rebuilt.seed, (int) request.seed);
            expect (rebuilt.quality == request.quality);
            expect (rebuilt.mode == request.mode);
        }

        beginTest ("AC: clicking Generate starts a run without freezing the caller");
        {
            ScopedClipCleanup cleanup;

            Harness harness;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            expect (connect (harness, server), "never connected");

            auto& panel = harness.panel();
            panel.getPromptEditor().setText ("kosmische arpeggios", true);
            expect (pumpUntil ([&] { return panel.getGenerateButton().isEnabled(); }));

            const auto before = juce::Time::getMillisecondCounter();
            panel.getGenerateButton().triggerClick();
            expect (pumpUntil ([&] { return harness.generation().isBusy(); }), "never started");
            const auto elapsed = juce::Time::getMillisecondCounter() - before;

            // AC: no DAW UI freeze — the click returns immediately, the work is
            // elsewhere. Generous bound; a synchronous submit+poll would be seconds.
            expect (elapsed < 1000, "the click blocked for " + juce::String ((int) elapsed) + "ms");

            // Controls lock while a run is in flight so the request can't drift.
            expect (! panel.getGenerateButton().isEnabled(), "Generate stayed live during a run");
            expect (panel.getCancelButton().isEnabled(), "Cancel was not offered");
            expect (! panel.getPromptEditor().isEnabled(), "prompt stayed editable during a run");
            expect (panel.getProgressBar().isVisible(), "no progress shown");

            panel.getCancelButton().triggerClick();
            expect (pumpUntil ([&] { return ! harness.generation().isBusy(); }, 30000), "cancel never settled");

            expect (pumpUntil ([&] { return panel.getPromptEditor().isEnabled(); }),
                    "controls stayed locked after the run ended");
            expect (! panel.getProgressBar().isVisible(), "progress stayed visible after the run");
        }

        beginTest ("closing and reopening the window shows the run still in flight");
        {
            ScopedClipCleanup cleanup;

            test::StubAceStepServer server;
            expect (server.start() != 0);

            PluginProcessor processor (nullptr, false);

            {
                PluginEditor first (processor);
                first.setSize (720, 640);

                server.setResponseFor ("/v1/stats", R"({"data":{"models":[{"name":"m"}]},"code":200})");
                server.setResponseFor ("/release_task", R"({"data":{"task_id":"t"},"code":200})");
                server.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

                ConnectionSettings settings;
                settings.serverUrl = server.getBaseUrl();
                processor.getConnectionManager().setSettings (settings);
                processor.getConnectionManager().testConnection();
                expect (pumpUntil ([&] { return processor.getConnectionManager().getStatus()
                                             == ConnectionManager::Status::Connected; }));

                first.getGenerationPanel().getPromptEditor().setText ("long job", true);
                expect (pumpUntil ([&] { return first.getGenerationPanel().getGenerateButton().isEnabled(); }));
                first.getGenerationPanel().getGenerateButton().triggerClick();
                expect (pumpUntil ([&] { return processor.getGenerationManager().isBusy(); }), "never started");
            }

            // Window closed and reopened while the job runs.
            PluginEditor second (processor);
            second.setSize (720, 640);

            expect (processor.getGenerationManager().isBusy(), "the run died with the editor");
            expect (! second.getGenerationPanel().getGenerateButton().isEnabled(),
                    "the reopened panel offered Generate during a run");
            expect (second.getGenerationPanel().getCancelButton().isEnabled(),
                    "the reopened panel did not offer Cancel");

            processor.getGenerationManager().cancel();
            expect (pumpUntil ([&] { return ! processor.getGenerationManager().isBusy(); }, 30000),
                    "cancel never settled");
        }
    }
};

static GenerationPanelTests generationPanelTests;

} // namespace acemusic
