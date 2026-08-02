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
      generationPanel (p.getGenerationManager(), p.getConnectionManager(), &p.getHostSync(),
                       &p.getMidiCapture(), &p.getSidechainCapture(), p.hasSidechainInput()),
      resultsPanel (p.getGenerationManager(), p.getClipPlayer(), p.getHostSync(),
                    p.getBackgroundQueue(), p.getSettings())
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
    // Three real panels need the room: the 520 default from US-23.1 left Results
    // squeezed to a single line once it had waveforms in it. The minimum is raised
    // for the same reason — below this the clip rows have nowhere to draw.
    // Results now carries clip rows AND the cache browser, so it needs roughly twice
    // the height it did in US-23.4. Raised again rather than letting either half be
    // a sliver.
    // Raised again for US-24.3: Generation gained a capture row and two host readouts,
    // and below this the Results panel had no room left for a clip row at all.
    setResizeLimits (560, 830, 1600, 1600);
    setSize (780, 950);
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

    // Both panels have real content now, so split the remaining space rather than
    // starving Results.
    // Raised from 230: the capture row and the two host readouts are new since US-23.3,
    // and below this the prompt box collapses to nothing.
    generationPanel.setBounds (area.removeFromTop (juce::jmax (280, area.getHeight() * 55 / 100)));
    area.removeFromTop (12);
    resultsPanel.setBounds (area);
}

} // namespace acemusic
