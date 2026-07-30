#include "PluginEditor.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

/**
    Drives the real widgets through the real editor, so these cover the wiring the
    acceptance criteria actually describe: typing a URL, clicking Test Connection,
    and reading the indicator and dropdown.

    Needs a display — `xvfb-run -a ctest` on a headless Linux box.
*/
class ConnectionPanelTests final : public juce::UnitTest
{
public:
    ConnectionPanelTests()
        : juce::UnitTest ("ConnectionPanel", "acemusic")
    {
    }

    bool pumpUntil (std::function<bool()> predicate, int timeoutMs = 10000)
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

    /** Editor over an offline processor — no real config file, no probe on load. */
    struct Harness
    {
        Harness()
            : processor (nullptr, false),
              editor (processor)
        {
            editor.setSize (720, 520);
        }

        ConnectionPanel& panel()               { return editor.getConnectionPanel(); }
        ConnectionManager& manager()           { return processor.getConnectionManager(); }

        PluginProcessor processor;
        PluginEditor editor;
    };

    void runTest() override
    {
        using Status = ConnectionManager::Status;

        beginTest ("shows the default URL and an idle indicator before any attempt");
        {
            Harness harness;

            expectEquals (harness.panel().getUrlEditor().getText(),
                          juce::String (ConnectionSettings::defaultServerUrl));
            expectEquals (harness.panel().getStatusLabel().getText(), juce::String ("Not connected"));
            expectEquals (harness.panel().getModelSelector().getNumItems(), 0);
            expect (harness.panel().getTestButton().isEnabled());
        }

        beginTest ("the API key field is masked");
        {
            Harness harness;
            expect (harness.panel().getApiKeyEditor().getPasswordCharacter() != 0,
                    "API key is shown in the clear");
        }

        beginTest ("AC: typing a URL and clicking Test turns the light green and fills the dropdown");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0, "could not bind a stub server port");

            Harness harness;
            auto& panel = harness.panel();

            // Type it, then click — the click must test what was typed, not the old value.
            panel.getUrlEditor().setText (server.getBaseUrl(), juce::sendNotification);
            panel.getTestButton().triggerClick();
            // Button::triggerClick() posts a command message — pump it through.
            expect (pumpUntil ([&] { return harness.manager().getStatus() != Status::Disconnected; }),
                    "the click never reached the button");

            expect (pumpUntil ([&] { return harness.manager().getStatus() != Status::Connecting; }),
                    "probe never completed");
            expect (pumpUntil ([&] { return panel.getModelSelector().getNumItems() == 2; }),
                    "dropdown was not populated, status says: " + panel.getStatusLabel().getText());

            expect (harness.manager().getStatus() == Status::Connected,
                    "expected Connected, got \"" + panel.getStatusLabel().getText() + "\"");

            // AC: the dropdown lists all models the server reported.
            expectEquals (panel.getModelSelector().getItemText (0), juce::String ("ace-step-1.5"));
            expectEquals (panel.getModelSelector().getItemText (1), juce::String ("ace-step-mini"));
            expect (panel.getModelSelector().getSelectedId() > 0, "no model was selected");

            // The indicator is actually green, read off the component that paints it.
            const auto colour = panel.getStatusLight().getCurrentColour();
            expect (colour.getGreen() > colour.getRed() && colour.getGreen() > colour.getBlue(),
                    "indicator is not green: " + colour.toDisplayString (true));
        }

        beginTest ("AC: with the server stopped the light goes red and says 'Server unreachable'");
        {
            const auto closedPort = test::findClosedPort();
            expect (closedPort != 0);

            Harness harness;
            auto& panel = harness.panel();

            panel.getUrlEditor().setText ("http://127.0.0.1:" + juce::String (closedPort), juce::sendNotification);
            panel.getTestButton().triggerClick();

            expect (pumpUntil ([&] { return harness.manager().getStatus() == Status::Error; }),
                    "never reached Error, status says: " + panel.getStatusLabel().getText());

            expectEquals (panel.getStatusLabel().getText(), juce::String ("Server unreachable"));

            const auto colour = panel.getStatusLight().getCurrentColour();
            expect (colour.getRed() > colour.getGreen() && colour.getRed() > colour.getBlue(),
                    "indicator is not red: " + colour.toDisplayString (true));

            expectEquals (panel.getModelSelector().getNumItems(), 0, "kept a model list after failing");
        }

        beginTest ("the Test button is disabled while a probe is in flight");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            Harness harness;
            auto& panel = harness.panel();

            panel.getUrlEditor().setText (server.getBaseUrl(), juce::sendNotification);
            // Hold the response so there is a real in-flight window to observe.
            server.setResponseDelayMs (1500);

            panel.getTestButton().triggerClick();

            expect (pumpUntil ([&] { return ! panel.getTestButton().isEnabled(); }, 1000),
                    "button was never disabled while a probe was in flight");

            expect (pumpUntil ([&] { return panel.getTestButton().isEnabled(); }),
                    "button was never re-enabled");
            expect (harness.manager().getStatus() == Status::Connected,
                    "expected Connected, got \"" + panel.getStatusLabel().getText() + "\"");
        }

        beginTest ("picking a model in the dropdown records it");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            Harness harness;
            auto& panel = harness.panel();

            panel.getUrlEditor().setText (server.getBaseUrl(), juce::sendNotification);
            panel.getTestButton().triggerClick();
            expect (pumpUntil ([&] { return panel.getModelSelector().getNumItems() == 2; }));

            // sendNotification on a ComboBox is an *async* update; Sync fires onChange now.
            panel.getModelSelector().setSelectedId (2, juce::sendNotificationSync);

            expectEquals (harness.manager().getSettings().modelId, juce::String ("ace-step-mini"));
        }

        beginTest ("closing and reopening the window shows the live status, not a blank panel");
        {
            // This is why connection state lives on the processor: the editor is
            // transient, the connection is not.
            test::StubAceStepServer server;
            expect (server.start() != 0);

            PluginProcessor processor (nullptr, false);

            {
                PluginEditor firstEditor (processor);
                firstEditor.setSize (720, 520);

                auto& panel = firstEditor.getConnectionPanel();
                panel.getUrlEditor().setText (server.getBaseUrl(), juce::sendNotification);
                panel.getTestButton().triggerClick();

                expect (pumpUntil ([&] { return panel.getModelSelector().getNumItems() == 2; }),
                        "first editor never connected");
            }

            // Window closed and reopened.
            PluginEditor secondEditor (processor);
            secondEditor.setSize (720, 520);

            auto& panel = secondEditor.getConnectionPanel();

            expectEquals (panel.getUrlEditor().getText(), server.getBaseUrl(),
                          "reopened panel lost the server URL");
            expectEquals (panel.getModelSelector().getNumItems(), 2,
                          "reopened panel lost the model list");
            expectEquals (panel.getStatusLabel().getText(), processor.getConnectionManager().getStatusMessage());

            const auto colour = panel.getStatusLight().getCurrentColour();
            expect (colour.getGreen() > colour.getRed(),
                    "reopened panel does not show the live green status");
        }

        beginTest ("an editor destroyed mid-probe does not crash");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            PluginProcessor processor (nullptr, false);

            {
                PluginEditor editor (processor);
                editor.setSize (720, 520);
                auto& panel = editor.getConnectionPanel();
                panel.getUrlEditor().setText (server.getBaseUrl(), juce::sendNotification);

                // Hold the response so the probe really is in flight when the editor goes.
                server.setResponseDelayMs (1200);
                panel.getTestButton().triggerClick();

                expect (pumpUntil ([&] { return processor.getConnectionManager().isBusy(); }, 2000),
                        "the probe never started");
                // editor dies with the probe in flight; the manager outlives it
            }

            expect (pumpUntil ([&] { return processor.getConnectionManager().getStatus() != Status::Connecting; }),
                    "probe never settled after the editor closed");
            expect (processor.getConnectionManager().getStatus() == Status::Connected,
                    "probe result was lost when the editor closed");
        }
    }
};

static ConnectionPanelTests connectionPanelTests;

} // namespace acemusic
