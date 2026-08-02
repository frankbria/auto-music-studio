#pragma once

#include "BackgroundTaskQueue.h"
#include "ClipCache.h"
#include "ClipPlayer.h"
#include "GenerationManager.h"
#include "HostSync.h"

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
    /** @param settings  resolves the configured cache path; null uses the default */
    ResultsPanel (GenerationManager&, ClipPlayer&, HostSync&, BackgroundTaskQueue&,
                  juce::PropertiesFile* settings = nullptr);
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
        void mouseUp (const juce::MouseEvent&) override;

        const juce::File& getFile() const noexcept            { return file; }
        juce::TextButton& getPlayButton() noexcept            { return playButton; }

        /** What a drop actually hands the host: the clip itself, or a tempo-matched
            copy of it once one has been built. */
        const juce::File& getDragFile() const noexcept        { return dragFile; }

        /** Builds (once, in the background) a copy of this clip at `hostBpm`, given it
            was generated at `clipBpm`. Either tempo being unknown, or the two already
            agreeing, drops the match and goes back to handing over the original.
            Cheap and idempotent — the panel calls this on every timer tick. */
        void ensureTempoMatch (double hostBpm, double clipBpm, BackgroundTaskQueue&);

        /** True once the waveform has finished loading. */
        bool hasWaveform() const;

        /** What a drag would hand to the host. Exposed because a real drag cannot be
            driven from a test. */
        juce::StringArray getDragPayload() const;

    private:
        void changeListenerCallback (juce::ChangeBroadcaster*) override;
        void timerCallback() override;

        juce::File file;

        /** Equal to `file` until a tempo match has been built for the host's tempo. */
        juce::File dragFile;

        /** The host tempo `dragFile` was built for; 0 when it is just the original. */
        double matchedToBpm = 0.0;
        bool matchInFlight = false;

        ClipPlayer& player;
        juce::AudioThumbnail thumbnail;
        juce::TextButton playButton { "Play" };
        juce::Label nameLabel;
        int clipIndex = 0;

        /** mouseDrag fires continuously while the button is held, so without this a
            gesture would try to start a new OS drag on every mouse move. */
        bool dragStarted = false;

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

    //==============================================================================
    // Cache browser (US-23.5).

    /** Re-reads the cache from disk. */
    void refreshCache();

    /** Applies whatever is typed in the cache path box. */
    void commitCachePath();

    /** Past generations, newest first, as last read. */
    const juce::Array<ClipCache::Entry>& getCacheEntries() const noexcept { return cacheEntries; }

    juce::ListBox& getHistoryList() noexcept                  { return historyList; }
    juce::TextButton& getDeleteButton() noexcept              { return deleteButton; }
    juce::TextButton& getClearCacheButton() noexcept          { return clearCacheButton; }
    juce::TextEditor& getCachePathEditor() noexcept           { return cachePathEditor; }
    juce::Label& getCacheSizeLabel() noexcept                 { return cacheSizeLabel; }
    ClipCache& getCache() noexcept                            { return cache; }

    /** Deletes the selected past generation. @returns false if nothing was selected. */
    bool deleteSelectedEntry();

private:
    void changeListenerCallback (juce::ChangeBroadcaster*) override;
    void timerCallback() override;
    void rebuildRows();

    /** Keeps every row's drop file in step with the host tempo. */
    void updateTempoMatches();

    /** Rows of past generations: prompt, when, how long, how big. */
    class HistoryModel final : public juce::ListBoxModel
    {
    public:
        explicit HistoryModel (ResultsPanel& ownerToUse) : owner (ownerToUse) {}

        int getNumRows() override;
        void paintListBoxItem (int row, juce::Graphics&, int width, int height, bool selected) override;
        void listBoxItemDoubleClicked (int row, const juce::MouseEvent&) override;

        /** Without this, clicking a row left Delete greyed out — the button was only
            ever updated by refreshCache(), so the ordinary flow (generate, click a
            row, click Delete) did not work. */
        void selectedRowsChanged (int lastRowSelected) override;

    private:
        ResultsPanel& owner;
    };

    GenerationManager& generation;
    ClipPlayer& player;
    HostSync& hostSync;
    BackgroundTaskQueue& queue;
    ClipCache cache;

    juce::AudioThumbnailCache thumbnailCache { 8 };

    juce::Label titleLabel;
    juce::Label statusLabel;
    juce::Label playheadLabel;
    juce::OwnedArray<ClipRow> clipRows;

    juce::Array<juce::File> history;

    juce::Label      historyTitle;
    HistoryModel     historyModel { *this };
    juce::ListBox    historyList { "cache", &historyModel };
    juce::TextButton deleteButton { "Delete" };
    juce::TextButton clearCacheButton { "Clear cache" };
    juce::Label      cacheSizeLabel;
    juce::Label      cachePathLabel;
    juce::TextEditor cachePathEditor;
    juce::Array<ClipCache::Entry> cacheEntries;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ResultsPanel)
};

} // namespace acemusic
