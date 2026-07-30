#include "ConnectionPanel.h"

namespace acemusic
{

namespace panelColours
{
    static const juce::Colour fill     { 0xff1d1d20 };
    static const juce::Colour edge     { 0xff34343a };
    static const juce::Colour text     { 0xffe9e9ec };
    static const juce::Colour textDim  { 0xff8b8b93 };
    static const juce::Colour field    { 0xff121214 };

    static const juce::Colour green    { 0xff3ec46d };
    static const juce::Colour amber    { 0xffe0b341 };
    static const juce::Colour red      { 0xffe0564a };
    static const juce::Colour idle     { 0xff5a5a63 };
}

//==============================================================================
void ConnectionPanel::StatusLight::setStatus (ConnectionManager::Status status)
{
    switch (status)
    {
        case ConnectionManager::Status::Connected:     colour = panelColours::green;  break;
        case ConnectionManager::Status::Connecting:    colour = panelColours::amber;  break;
        case ConnectionManager::Status::Error:         colour = panelColours::red;    break;
        case ConnectionManager::Status::Disconnected:  colour = panelColours::idle;   break;
    }

    repaint();
}

void ConnectionPanel::StatusLight::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat().reduced (2.0f);
    const auto diameter = juce::jmin (bounds.getWidth(), bounds.getHeight());
    bounds = bounds.withSizeKeepingCentre (diameter, diameter);

    g.setColour (colour);
    g.fillEllipse (bounds);

    g.setColour (colour.darker (0.6f));
    g.drawEllipse (bounds, 1.0f);
}

//==============================================================================
ConnectionPanel::ConnectionPanel (ConnectionManager& managerToUse)
    : manager (managerToUse)
{
    auto styleLabel = [] (juce::Label& label, const juce::String& text, bool dim)
    {
        label.setText (text, juce::dontSendNotification);
        label.setFont (juce::FontOptions (dim ? 12.0f : 13.0f, dim ? juce::Font::plain : juce::Font::bold));
        label.setColour (juce::Label::textColourId, dim ? panelColours::textDim : panelColours::text);
    };

    auto styleEditor = [] (juce::TextEditor& editor)
    {
        editor.setColour (juce::TextEditor::backgroundColourId, panelColours::field);
        editor.setColour (juce::TextEditor::textColourId, panelColours::text);
        editor.setColour (juce::TextEditor::outlineColourId, panelColours::edge);
        editor.setFont (juce::FontOptions (13.0f));
    };

    styleLabel (titleLabel, "CONNECTION", true);
    addAndMakeVisible (titleLabel);

    styleLabel (urlLabel, "Server URL", true);
    addAndMakeVisible (urlLabel);
    styleEditor (urlEditor);
    addAndMakeVisible (urlEditor);

    styleLabel (apiKeyLabel, "API key (optional)", true);
    addAndMakeVisible (apiKeyLabel);
    styleEditor (apiKeyEditor);
    apiKeyEditor.setPasswordCharacter ((juce::juce_wchar) 0x2022);
    apiKeyEditor.setTextToShowWhenEmpty ("none", panelColours::textDim);
    addAndMakeVisible (apiKeyEditor);

    // Editing either field is what commits it — no separate Save button, and the
    // "Test Connection" click commits too (below) so a user who types and clicks
    // straight away tests what they typed.
    urlEditor.onFocusLost    = [this] { commitSettingsFromEditors(); };
    urlEditor.onReturnKey    = [this] { commitSettingsFromEditors(); };
    apiKeyEditor.onFocusLost = [this] { commitSettingsFromEditors(); };
    apiKeyEditor.onReturnKey = [this] { commitSettingsFromEditors(); };

    testButton.onClick = [this]
    {
        commitSettingsFromEditors();
        manager.testConnection();
    };
    addAndMakeVisible (testButton);

    addAndMakeVisible (statusLight);
    styleLabel (statusLabel, "", true);
    addAndMakeVisible (statusLabel);

    styleLabel (modelLabel, "Model", true);
    addAndMakeVisible (modelLabel);

    modelSelector.setTextWhenNoChoicesAvailable ("Connect to list models");
    modelSelector.setColour (juce::ComboBox::backgroundColourId, panelColours::field);
    modelSelector.setColour (juce::ComboBox::textColourId, panelColours::text);
    modelSelector.setColour (juce::ComboBox::outlineColourId, panelColours::edge);
    modelSelector.onChange = [this]
    {
        if (modelSelector.getSelectedId() > 0)
            manager.setSelectedModel (modelSelector.getText());
    };
    addAndMakeVisible (modelSelector);

    manager.addChangeListener (this);
    refreshFromManager();
}

ConnectionPanel::~ConnectionPanel()
{
    manager.removeChangeListener (this);
}

void ConnectionPanel::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat();

    g.setColour (panelColours::fill);
    g.fillRoundedRectangle (bounds, 6.0f);

    g.setColour (panelColours::edge);
    g.drawRoundedRectangle (bounds.reduced (0.5f), 6.0f, 1.0f);
}

void ConnectionPanel::resized()
{
    auto area = getLocalBounds().reduced (12, 8);

    titleLabel.setBounds (area.removeFromTop (18));
    area.removeFromTop (6);

    // Row 1: URL and API key side by side.
    auto row = area.removeFromTop (44);
    auto urlArea = row.removeFromLeft (juce::roundToInt (row.getWidth() * 0.58f));
    urlLabel.setBounds (urlArea.removeFromTop (16));
    urlEditor.setBounds (urlArea.reduced (0, 1));

    row.removeFromLeft (8);
    apiKeyLabel.setBounds (row.removeFromTop (16));
    apiKeyEditor.setBounds (row.reduced (0, 1));

    area.removeFromTop (8);

    // Row 2: test button, indicator, model dropdown.
    row = area.removeFromTop (26);
    testButton.setBounds (row.removeFromLeft (130));
    row.removeFromLeft (10);
    statusLight.setBounds (row.removeFromLeft (18));
    row.removeFromLeft (4);

    auto modelArea = row.removeFromRight (juce::jmin (220, row.getWidth() / 2));
    modelLabel.setBounds (modelArea.removeFromLeft (44));
    modelSelector.setBounds (modelArea);

    statusLabel.setBounds (row.withTrimmedRight (8));
}

void ConnectionPanel::changeListenerCallback (juce::ChangeBroadcaster*)
{
    refreshFromManager();
}

void ConnectionPanel::refreshFromManager()
{
    const auto settings = manager.getSettings();

    // Don't fight the user's cursor while they are mid-edit.
    if (! urlEditor.hasKeyboardFocus (true))
        urlEditor.setText (settings.serverUrl, juce::dontSendNotification);

    if (! apiKeyEditor.hasKeyboardFocus (true))
        apiKeyEditor.setText (settings.apiKey, juce::dontSendNotification);

    statusLight.setStatus (manager.getStatus());
    statusLabel.setText (manager.getStatusMessage(), juce::dontSendNotification);
    testButton.setEnabled (! manager.isBusy());

    const auto& models = manager.getModels();

    // Rebuild only when the list actually changed — otherwise every status broadcast
    // would reset the user's selection.
    juce::StringArray current;
    for (int i = 0; i < modelSelector.getNumItems(); ++i)
        current.add (modelSelector.getItemText (i));

    if (current != models)
    {
        modelSelector.clear (juce::dontSendNotification);

        for (int i = 0; i < models.size(); ++i)
            modelSelector.addItem (models[i], i + 1);
    }

    // Only touch the selection when it's actually wrong — reassigning it on every
    // status broadcast would make an open dropdown jump under the user's cursor.
    const auto index = models.indexOf (settings.modelId);
    const auto wantedId = index >= 0 ? index + 1 : 0;

    if (modelSelector.getSelectedId() != wantedId)
        modelSelector.setSelectedId (wantedId, juce::dontSendNotification);
}

void ConnectionPanel::commitSettingsFromEditors()
{
    auto settings = manager.getSettings();
    settings.serverUrl = urlEditor.getText().trim();
    settings.apiKey = apiKeyEditor.getText();

    if (settings != manager.getSettings())
        manager.setSettings (settings);
}

} // namespace acemusic
