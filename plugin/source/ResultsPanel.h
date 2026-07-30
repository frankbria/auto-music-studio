#pragma once

#include "ClipPlayer.h"
#include "GenerationManager.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    Shows the clips a generation produced: a waveform each, play/stop, and a drag
    handle to pull the file into the host's timeline.

    **Why drag-and-drop and not an "Insert to Track" button.** VST3 gives a plugin no
    way to place audio on the host timeline or to create a track — it can read the
    transport (juce::AudioPlayHead) but not write to the arrangement. Dragging the
    file out is what every generative plugin does instead, and it works in essentially
    any DAW. The panel shows the current playhead so the drop can be lined up, since
    reading it *is* possible. See the amended acceptance criteria on #318.
*/
class ResultsPanel final : public juce::Component,
                           private juce::ChangeListener,
                           private juce::Timer
{
public:
    ResultsPanel (GenerationManager&, ClipPlayer&, juce::AudioProcessor&);
    ~ResultsPanel() override;

    void paint (juce::Graphics&) override;
    void resized() override;

    /** One clip: waveform, play/stop, and the drag source. */
    class ClipRow final : public juce::Component,
                          private juce::ChangeListener,
                          private juce::Timer
    {
    public:
        ClipRow (const juce::File&, ClipPlayer&, juce::AudioFormatManager&,
                 juce::AudioThumbnailCache&, int index);
        ~ClipRow() override;

        void paint (juce::Graphics&) override;
        void resized() override;
        void mouseDrag (const juce::MouseEvent&) override;

        const juce::File& getFile() const noexcept            { return file; }
        juce::TextButton& getPlayButton() noexcept            { return playButton; }

        /** True once the waveform has finished loading. */
        bool hasWaveform() const;

        /** What a drag would hand to the host. Exposed because a real drag cannot be
            driven from a test. */
        juce::StringArray getDragPayload() const;

    private:
        void changeListenerCallback (juce::ChangeBroadcaster*) override;
        void timerCallback() override;

        juce::File file;
        ClipPlayer& player;
        juce::AudioThumbnail thumbnail;
        juce::TextButton playButton { "Play" };
        juce::Label nameLabel;
        int clipIndex = 0;

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ClipRow)
    };

    //==============================================================================
    // Test seams.
    int getNumClipRows() const noexcept                       { return clipRows.size(); }
    ClipRow* getClipRow (int index) const                     { return clipRows[index]; }
    juce::Label& getStatusLabel() noexcept                    { return statusLabel; }
    juce::Label& getPlayheadLabel() noexcept                  { return playheadLabel; }

    /** Every clip this session has produced, newest generation last. */
    const juce::Array<juce::File>& getHistory() const noexcept { return history; }

private:
    void changeListenerCallback (juce::ChangeBroadcaster*) override;
    void timerCallback() override;
    void rebuildRows();

    GenerationManager& generation;
    ClipPlayer& player;
    juce::AudioProcessor& processor;

    juce::AudioThumbnailCache thumbnailCache { 8 };

    juce::Label titleLabel;
    juce::Label statusLabel;
    juce::Label playheadLabel;
    juce::OwnedArray<ClipRow> clipRows;

    juce::Array<juce::File> history;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ResultsPanel)
};

} // namespace acemusic
