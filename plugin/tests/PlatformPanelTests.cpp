#include "ClipCache.h"
#include "PluginEditor.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

/** The platform panel driven through the real editor (US-24.5).

    These deliberately go through the panel rather than PlatformClient: the client
    being correct says nothing about whether the panel calls it, which is the mistake
    that shipped US-24.3 and US-24.4 non-functional. */
class PlatformPanelTests final : public juce::UnitTest
{
public:
    PlatformPanelTests()
        : juce::UnitTest ("PlatformPanel", "acemusic")
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

    /** Throwaway settings so nothing touches the user's real config or cache. */
    struct ScopedSettings
    {
        ScopedSettings()
        {
            root = juce::File::getSpecialLocation (juce::File::tempDirectory)
                       .getChildFile ("acemusic-platformpanel-"
                                      + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            root.createDirectory();

            juce::PropertiesFile::Options options;
            options.applicationName = "PlatformPanelTest";
            options.filenameSuffix = ".settings";
            options.storageFormat = juce::PropertiesFile::storeAsXML;

            properties = std::make_unique<juce::PropertiesFile> (root.getChildFile ("t.settings"), options);
            properties->setValue (ClipCache::cachePathKey, root.getChildFile ("clips").getFullPathName());
            properties->saveIfNeeded();
        }

        ~ScopedSettings()
        {
            properties.reset();
            root.deleteRecursively();
        }

        juce::File root;
        std::unique_ptr<juce::PropertiesFile> properties;
    };

    static void serveWorkspacesAndClips (test::StubAceStepServer& server)
    {
        server.setResponseFor ("/workspaces",
                               R"({"workspaces":[{"id":"w1","name":"Demos"},{"id":"w2","name":"Album"}]})");
        server.setResponseFor ("/clips",
                               R"({"clips":[{"id":"c1","title":"Dub Sketch","format":"wav","duration":30.0,
                                   "bpm":118,"key":"C minor","style_tags":["dub"]}],"total":1})");
        server.setResponseFor ("/audio", "RIFF....WAVEfmt imported audio payload");
    }

    void runTest() override
    {
        beginTest ("every status the panel can show stays ASCII");
        {
            // AGENTS.md: a non-ASCII literal renders as mojibake in the plugin UI, and a
            // test comparing it against another literal written the same way will not
            // notice. So the bytes are checked, not the text.
            const auto isAsciiOnly = [] (const juce::String& text)
            {
                for (auto c : text)
                    if (c < 32 || c > 126)
                        return false;

                return true;
            };

            ScopedSettings settings;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 401 Unauthorized");

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);
            auto& panel = editor.getPlatformPanel();

            // Drive it through the states that produce user-facing text.
            const auto check = [&] (const juce::String& what)
            {
                const auto text = panel.getStatusLabel().getText();
                expect (isAsciiOnly (text), "non-ASCII in " + what + ": " + text);
            };

            check ("the unconfigured state");

            panel.getUrlEditor().setText (server.getBaseUrl(), false);
            panel.connect();
            check ("the connecting state");

            expect (pumpUntil ([&] { return panel.getStatusLabel().getText().containsIgnoreCase ("key"); }, 10000));
            check ("a rejected key");

            // And the no-TLS message, which is a literal rather than a runtime string.
            expect (isAsciiOnly (Platform::findUrlProblem ("")), "non-ASCII in the empty-URL message");
        }

        beginTest ("AC: with no platform configured the plugin is unaffected and says so");
        {
            ScopedSettings settings;
            // No platform URL saved, so this is a fresh install.
            settings.properties->removeValue (Platform::urlKey);
            settings.properties->saveIfNeeded();

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getPlatformPanel();

            expect (! panel.isConnected(), "reported connected with nothing configured");
            expect (! panel.getImportButton().isEnabled(), "Import was live with no connection");
            expect (! panel.getPushButton().isEnabled(), "Push was live with no connection");

            // The default URL is pre-filled, so "no credentials" here means the panel
            // is simply not connected — and it must not look broken.
            expect (! panel.getStatusLabel().getText().containsIgnoreCase ("error"),
                    "an unconfigured platform reads as an error: " + panel.getStatusLabel().getText());

            // And everything else still works: the generation panel is untouched.
            editor.getGenerationPanel().getPromptEditor().setText ("still works", true);
            expectEquals (editor.getGenerationPanel().buildRequest().prompt, juce::String ("still works"));
        }

        beginTest ("AC: connecting lists the workspaces and their clips");
        {
            ScopedSettings settings;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            serveWorkspacesAndClips (server);

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getPlatformPanel();
            panel.getUrlEditor().setText (server.getBaseUrl(), false);
            panel.getApiKeyEditor().setText ("token", false);

            panel.connect();

            expect (pumpUntil ([&] { return panel.isConnected(); }, 10000),
                    "never connected: " + panel.getStatusLabel().getText());
            expectEquals (panel.getWorkspaceSelector().getNumItems(), 2);
            expectEquals (panel.getWorkspaceSelector().getItemText (0), juce::String ("Demos"));

            // Selecting a workspace pulls its clips without a second click.
            expect (pumpUntil ([&] { return panel.getClips().size() == 1; }, 10000),
                    "clips never arrived: " + panel.getStatusLabel().getText());
            expectEquals (panel.getClips()[0].title, juce::String ("Dub Sketch"));
            expectEquals (panel.getClips()[0].bpm, 118);
        }

        beginTest ("AC: importing a clip downloads it and shows it in Results");
        {
            ScopedSettings settings;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            serveWorkspacesAndClips (server);

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getPlatformPanel();
            panel.getUrlEditor().setText (server.getBaseUrl(), false);
            panel.connect();
            expect (pumpUntil ([&] { return panel.getClips().size() == 1; }, 10000));

            panel.getClipList().selectRow (0);
            panel.importSelectedClip();

            // The clip reaches the Results panel, which is what makes it draggable —
            // the only insertion a VST3 plugin has (#318).
            expect (pumpUntil ([&] { return editor.getResultsPanel().getNumClipRows() == 1; }, 20000),
                    "the imported clip never reached Results: " + panel.getStatusLabel().getText());

            const auto imported = editor.getResultsPanel().getClipRow (0)->getFile();
            expect (imported.existsAsFile(), "the imported clip is not on disk");
            expect (imported.getSize() > 0);
            expect (imported.getFullPathName().contains ("platform"),
                    "imported outside the platform cache: " + imported.getFullPathName());
        }

        beginTest ("AC: a platform outage does not touch local generation");
        {
            // The criterion most likely to regress, and the reason the platform client
            // shares no state with the generation path.
            ScopedSettings settings;

            juce::String deadUrl;
            {
                test::StubAceStepServer dead;
                expect (dead.start() != 0);
                deadUrl = dead.getBaseUrl();
            }   // stopped

            test::StubAceStepServer aceStep;
            expect (aceStep.start() != 0);
            aceStep.setResponseFor ("/v1/stats", R"({"data":{"models":[{"name":"m"}]},"code":200})");
            aceStep.setResponseFor ("/release_task", R"({"data":{"task_id":"t"},"code":200})");
            aceStep.setResponseFor ("/query_result", R"({"data":[{"status":0}],"code":200})");

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getPlatformPanel();
            panel.getUrlEditor().setText (deadUrl, false);
            panel.connect();

            // Meanwhile the local ACE-Step connection comes up and a generation starts,
            // while the platform request is still failing.
            ConnectionSettings connection;
            connection.serverUrl = aceStep.getBaseUrl();
            processor.getConnectionManager().setSettings (connection);
            processor.getConnectionManager().testConnection();

            expect (pumpUntil ([&] { return processor.getConnectionManager().getStatus()
                                         == ConnectionManager::Status::Connected; }, 20000),
                    "the local server never connected while the platform was down");

            auto& generationPanel = editor.getGenerationPanel();
            generationPanel.getPromptEditor().setText ("local generation", true);
            expect (pumpUntil ([&] { return generationPanel.getGenerateButton().isEnabled(); }, 10000),
                    "Generate stayed disabled because the platform was unreachable");

            generationPanel.getGenerateButton().triggerClick();
            expect (pumpUntil ([&] { return processor.getGenerationManager().isBusy(); }, 10000),
                    "a local generation could not start while the platform was down");

            // And the platform failure is reported, not swallowed.
            expect (pumpUntil ([&] { return ! panel.isConnected()
                                            && panel.getStatusLabel().getText().isNotEmpty(); }, 20000));
            expect (! panel.getStatusLabel().getText().contains ("HTTP 0"),
                    "unactionable platform error: " + panel.getStatusLabel().getText());

            processor.getGenerationManager().cancel();
            expect (pumpUntil ([&] { return ! processor.getGenerationManager().isBusy(); }, 30000));
        }

        beginTest ("credentials persist, so they survive the window closing");
        {
            ScopedSettings settings;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            serveWorkspacesAndClips (server);

            const auto url = server.getBaseUrl();
            PluginProcessor processor (std::move (settings.properties), false);

            {
                PluginEditor first (processor);
                first.setSize (860, 1080);
                first.getPlatformPanel().getUrlEditor().setText (url, false);
                first.getPlatformPanel().getApiKeyEditor().setText ("saved-token", false);
                first.getPlatformPanel().connect();
                expect (pumpUntil ([&] { return first.getPlatformPanel().isConnected(); }, 10000));
            }

            PluginEditor second (processor);
            second.setSize (860, 1080);

            expectEquals (second.getPlatformPanel().getUrlEditor().getText(), url,
                          "the platform URL did not persist");
            expectEquals (second.getPlatformPanel().getApiKeyEditor().getText(),
                          juce::String ("saved-token"), "the API key did not persist");
        }

        beginTest ("a rejected key is reported on the panel, not swallowed");
        {
            ScopedSettings settings;
            test::StubAceStepServer server;
            expect (server.start() != 0);
            server.setStatusLine ("HTTP/1.1 401 Unauthorized");

            PluginProcessor processor (std::move (settings.properties), false);
            PluginEditor editor (processor);
            editor.setSize (860, 1080);

            auto& panel = editor.getPlatformPanel();
            panel.getUrlEditor().setText (server.getBaseUrl(), false);
            panel.getApiKeyEditor().setText ("wrong", false);
            panel.connect();

            expect (pumpUntil ([&] { return panel.getStatusLabel().getText().containsIgnoreCase ("key"); }, 10000),
                    "the rejected key was not reported: " + panel.getStatusLabel().getText());
            expect (! panel.isConnected());
        }
    }
};

static PlatformPanelTests platformPanelTests;

} // namespace acemusic
