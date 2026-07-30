#pragma once

#include "ConnectionManager.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    The connection UI: server URL, optional API key, a Test Connection button, a
    traffic-light indicator with a message, and the model dropdown.

    Holds no connection state of its own — it renders whatever ConnectionManager
    currently says and pushes edits back into it, so closing and reopening the plugin
    window shows the live status rather than a blank panel.
*/
class ConnectionPanel final : public juce::Component,
                              private juce::ChangeListener
{
public:
    explicit ConnectionPanel (ConnectionManager&);
    ~ConnectionPanel() override;

    void paint (juce::Graphics&) override;
    void resized() override;

    /** A green/amber/red dot. Exposed so tests can read the colour that is actually
        being drawn rather than inferring it. */
    class StatusLight final : public juce::Component
    {
    public:
        StatusLight() = default;

        void setStatus (ConnectionManager::Status);
        juce::Colour getCurrentColour() const noexcept        { return colour; }
        void paint (juce::Graphics&) override;

    private:
        juce::Colour colour { juce::Colours::grey };

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (StatusLight)
    };

    //==============================================================================
    // Test seams — these are the widgets the acceptance criteria talk about.
    juce::TextEditor&  getUrlEditor() noexcept                { return urlEditor; }
    juce::TextEditor&  getApiKeyEditor() noexcept             { return apiKeyEditor; }
    juce::TextButton&  getTestButton() noexcept               { return testButton; }
    juce::ComboBox&    getModelSelector() noexcept            { return modelSelector; }
    StatusLight&       getStatusLight() noexcept              { return statusLight; }
    juce::Label&       getStatusLabel() noexcept              { return statusLabel; }

private:
    void changeListenerCallback (juce::ChangeBroadcaster*) override;
    void refreshFromManager();
    void commitSettingsFromEditors();

    ConnectionManager& manager;

    juce::Label      titleLabel;
    juce::Label      urlLabel;
    juce::TextEditor urlEditor;
    juce::Label      apiKeyLabel;
    juce::TextEditor apiKeyEditor;
    juce::TextButton testButton { "Test Connection" };
    StatusLight      statusLight;
    juce::Label      statusLabel;
    juce::Label      modelLabel;
    juce::ComboBox   modelSelector;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ConnectionPanel)
};

} // namespace acemusic
