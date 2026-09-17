#pragma once

#include "ConnectionPanel.h"
#include "GenerationPanel.h"
#include "PlatformPanel.h"
#include "ResultsPanel.h"
#include "PluginProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    Plugin UI: name, version, and the Connection (US-23.2), Generation (US-23.3) and
    Results (US-23.4) panels.
*/
class PluginEditor final : public juce::AudioProcessorEditor
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    juce::Label titleLabel;
    juce::Label versionLabel;

    ConnectionPanel  connectionPanel;
    GenerationPanel  generationPanel;
    ResultsPanel     resultsPanel;
    PlatformPanel    platformPanel;

public:
    /** Test seam — lets a test drive the real widgets rather than re-deriving them. */
    ConnectionPanel& getConnectionPanel() noexcept            { return connectionPanel; }
    GenerationPanel& getGenerationPanel() noexcept            { return generationPanel; }
    PlatformPanel& getPlatformPanel() noexcept          { return platformPanel; }
    ResultsPanel& getResultsPanel() noexcept                  { return resultsPanel; }

private:

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};

} // namespace acemusic
