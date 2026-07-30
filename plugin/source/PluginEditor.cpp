#include "PluginEditor.h"

namespace acemusic
{

namespace colours
{
    static const juce::Colour background { 0xff141416 };
    static const juce::Colour panelFill  { 0xff1d1d20 };
    static const juce::Colour panelEdge  { 0xff34343a };
    static const juce::Colour text       { 0xffe9e9ec };
    static const juce::Colour textDim    { 0xff8b8b93 };
}

//==============================================================================
PluginEditor::PluginEditor (PluginProcessor& p)
    : juce::AudioProcessorEditor (&p),
      connectionPanel (p.getConnectionManager()),
      generationPanel (p.getGenerationManager(), p.getConnectionManager())
{
    titleLabel.setText (p.getName(), juce::dontSendNotification);
    titleLabel.setFont (juce::FontOptions (20.0f, juce::Font::bold));
    titleLabel.setColour (juce::Label::textColourId, colours::text);
    addAndMakeVisible (titleLabel);

    versionLabel.setText ("v" + PluginProcessor::getPluginVersion(), juce::dontSendNotification);
    versionLabel.setFont (juce::FontOptions (13.0f));
    versionLabel.setColour (juce::Label::textColourId, colours::textDim);
    versionLabel.setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (versionLabel);

    addAndMakeVisible (connectionPanel);
    addAndMakeVisible (generationPanel);
    addAndMakeVisible (resultsPanel);

    setResizable (true, true);
    setResizeLimits (480, 360, 1600, 1200);
    setSize (720, 520);
}

PluginEditor::~PluginEditor() = default;

void PluginEditor::paint (juce::Graphics& g)
{
    g.fillAll (colours::background);
}

void PluginEditor::resized()
{
    auto area = getLocalBounds().reduced (16);

    auto header = area.removeFromTop (28);
    versionLabel.setBounds (header.removeFromRight (80));
    titleLabel.setBounds (header);

    area.removeFromTop (12);

    // Connection is a fixed-height strip; Generation and Results split the rest.
    connectionPanel.setBounds (area.removeFromTop (132));
    area.removeFromTop (12);

    // Generation needs the room now that it has real controls; Results is still a
    // placeholder until US-23.4.
    generationPanel.setBounds (area.removeFromTop (juce::jmax (240, area.getHeight() * 2 / 3)));
    area.removeFromTop (12);
    resultsPanel.setBounds (area);
}

//==============================================================================
PluginEditor::PlaceholderPanel::PlaceholderPanel (juce::String panelTitle)
    : title (std::move (panelTitle))
{
}

void PluginEditor::PlaceholderPanel::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat();

    g.setColour (colours::panelFill);
    g.fillRoundedRectangle (bounds, 6.0f);

    g.setColour (colours::panelEdge);
    g.drawRoundedRectangle (bounds.reduced (0.5f), 6.0f, 1.0f);

    g.setColour (colours::textDim);
    g.setFont (juce::FontOptions (13.0f, juce::Font::bold));
    g.drawText (title.toUpperCase(),
                getLocalBounds().reduced (12, 8).removeFromTop (18),
                juce::Justification::centredLeft);
}

} // namespace acemusic
