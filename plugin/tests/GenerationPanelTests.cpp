#include "ClipCache.h"
#include "FakePlayHead.h"
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

            Harness harness { std::move (cleanup.properties) };
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

            PluginProcessor processor (std::move (cleanup.properties), false);

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

        //======================================================================
        // US-24.1 — host tempo sync.

        beginTest ("AC: opening the plugin in a 120 BPM project auto-fills BPM with 120");
        {
            PluginProcessor processor (nullptr, false);

            // The host has already told the plugin its tempo by the time the window
            // opens, which is the ordering a DAW actually produces.
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();

            // Filled at construction, not half a second later on the first timer tick.
            expectEquals (panel.getBpmEditor().getText(), juce::String ("120"),
                          "the BPM field did not pick up the host tempo on open");
            expect (panel.isBpmSynced());
            expect (panel.getSyncLabel().getText().contains ("120"),
                    "the sync indicator did not name the host tempo: "
                        + panel.getSyncLabel().getText());

            // And it reaches the request, so a generation actually asks for 120.
            panel.getPromptEditor().setText ("anything", true);
            expectEquals (panel.buildRequest().bpm, 120);
        }

        beginTest ("AC: changing the DAW tempo updates the plugin's BPM field");
        {
            PluginProcessor processor (nullptr, false);
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();
            expectEquals (panel.getBpmEditor().getText(), juce::String ("120"));

            // The musician drags the tempo in the DAW mid-session.
            playHead.bpm = 90.0;
            processor.getHostSync().captureFrom (&playHead);

            expect (pumpUntil ([&] { return panel.getBpmEditor().getText() == "90"; }, 5000),
                    "the BPM field stayed at " + panel.getBpmEditor().getText()
                        + " after the host moved to 90");
            expect (panel.isBpmSynced(), "following the host cancelled its own sync");
        }

        beginTest ("AC: a manual BPM override disables auto-sync, with a visual indicator");
        {
            PluginProcessor processor (nullptr, false);
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();

            const auto syncedText = panel.getSyncLabel().getText();

            // The user types their own tempo. TextEditor posts its change notification
            // rather than calling it inline, so this settles on the message loop.
            panel.getBpmEditor().setText ("100", true);

            expect (pumpUntil ([&] { return ! panel.isBpmSynced(); }, 5000),
                    "typing a BPM did not take the field off sync");
            expect (panel.getSyncLabel().getText() != syncedText,
                    "the indicator did not change when sync was turned off");
            expect (panel.getSyncLabel().getText().containsIgnoreCase ("manual"),
                    "the indicator does not say the BPM is manual: "
                        + panel.getSyncLabel().getText());

            // And the host must no longer be able to overwrite it.
            playHead.bpm = 140.0;
            processor.getHostSync().captureFrom (&playHead);

            expect (! pumpUntil ([&] { return panel.getBpmEditor().getText() != "100"; }, 1500),
                    "the host overwrote a manually entered BPM");
            expectEquals (panel.getBpmEditor().getText(), juce::String ("100"));
            expectEquals (panel.buildRequest().bpm, 100);
        }

        beginTest ("clearing the BPM field resumes host sync");
        {
            PluginProcessor processor (nullptr, false);
            test::FakePlayHead playHead;
            playHead.bpm = 128.0;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();

            panel.getBpmEditor().setText ("100", true);
            expect (pumpUntil ([&] { return ! panel.isBpmSynced(); }, 5000),
                    "typing a BPM did not take the field off sync");

            // Back to the "Auto" placeholder — the panel's existing convention for
            // "let something else decide", and the only way back to sync.
            panel.getBpmEditor().setText ("", true);
            expect (pumpUntil ([&] { return panel.isBpmSynced(); }, 5000),
                    "clearing the field did not resume sync");

            expect (pumpUntil ([&] { return panel.getBpmEditor().getText() == "128"; }, 5000),
                    "the host tempo did not come back after resyncing");
        }

        beginTest ("a host that reports no tempo leaves BPM on Auto and says so");
        {
            PluginProcessor processor (nullptr, false);
            test::FakePlayHead playHead;
            playHead.reportsPosition = false;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();

            // No invented default: an unknown host tempo stays Auto, which is what the
            // server treats as "you choose".
            expect (panel.getBpmEditor().getText().isEmpty(),
                    "a tempo was invented for a silent host: " + panel.getBpmEditor().getText());
            expect (panel.buildRequest().bpm < 0);
            expect (panel.getSyncLabel().getText().containsIgnoreCase ("no host tempo"),
                    "the indicator did not report the missing tempo: "
                        + panel.getSyncLabel().getText());
        }

        beginTest ("applying a request with its own BPM takes the field off sync");
        {
            PluginProcessor processor (nullptr, false);
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            processor.getHostSync().captureFrom (&playHead);

            PluginEditor editor (processor);
            editor.setSize (720, 640);
            auto& panel = editor.getGenerationPanel();

            GenerationRequest request;
            request.prompt = "recalled preset";
            request.bpm = 174;
            panel.applyRequest (request);

            expect (! panel.isBpmSynced(), "a recalled BPM was left on sync");
            expect (! pumpUntil ([&] { return panel.getBpmEditor().getText() != "174"; }, 1500),
                    "the host overwrote a recalled BPM");

            // A request that left BPM on Auto hands the field back to the host.
            request.bpm = -1;
            panel.applyRequest (request);
            expect (panel.isBpmSynced());
            expect (pumpUntil ([&] { return panel.getBpmEditor().getText() == "120"; }, 5000),
                    "an Auto-BPM request did not resume host sync");
        }
    }
};

static GenerationPanelTests generationPanelTests;

} // namespace acemusic
