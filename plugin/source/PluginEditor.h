#pragma once

#include "ConnectionPanel.h"
#include "PluginProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    Plugin UI: name, version, the live Connection panel (US-23.2), and the two panels
    still to come — Generation (US-23.3) and Results (US-23.4).
*/
class PluginEditor final : public juce::AudioProcessorEditor
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    /** An outlined box with a title, standing in for a panel not yet built. */
    class PlaceholderPanel final : public juce::Component
    {
    public:
        explicit PlaceholderPanel (juce::String panelTitle);
        void paint (juce::Graphics&) override;

    private:
        juce::String title;

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PlaceholderPanel)
    };

    juce::Label titleLabel;
    juce::Label versionLabel;

    ConnectionPanel  connectionPanel;
    PlaceholderPanel generationPanel { "Generation" };
    PlaceholderPanel resultsPanel    { "Results" };

public:
    /** Test seam — lets a test drive the real widgets rather than re-deriving them. */
    ConnectionPanel& getConnectionPanel() noexcept            { return connectionPanel; }

private:

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};

} // namespace acemusic
