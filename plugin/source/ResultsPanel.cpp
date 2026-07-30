#include "ResultsPanel.h"

namespace acemusic
{

namespace resultColours
{
    static const juce::Colour fill    { 0xff1d1d20 };
    static const juce::Colour edge    { 0xff34343a };
    static const juce::Colour text    { 0xffe9e9ec };
    static const juce::Colour textDim { 0xff8b8b93 };
    static const juce::Colour wave    { 0xff3ec46d };
    static const juce::Colour rowFill { 0xff121214 };
}

//==============================================================================
ResultsPanel::ClipRow::ClipRow (const juce::File& fileToShow,
                                ClipPlayer& playerToUse,
                                juce::AudioFormatManager& formats,
                                juce::AudioThumbnailCache& cache,
                                int index)
    : file (fileToShow),
      player (playerToUse),
      thumbnail (512, formats, cache),
      clipIndex (index)
{
    thumbnail.addChangeListener (this);
    thumbnail.setSource (new juce::FileInputSource (file));

    nameLabel.setText ("Clip " + juce::String (index + 1), juce::dontSendNotification);
    nameLabel.setFont (juce::FontOptions (12.0f));
    nameLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    addAndMakeVisible (nameLabel);

    playButton.onClick = [this] { player.toggle (file); };
    addAndMakeVisible (playButton);

    setMouseCursor (juce::MouseCursor::DraggingHandCursor);

    // Only to keep the play/stop label and playback position honest.
    startTimerHz (10);
}

ResultsPanel::ClipRow::~ClipRow()
{
    stopTimer();
    thumbnail.removeChangeListener (this);
}

bool ResultsPanel::ClipRow::hasWaveform() const
{
    return thumbnail.getTotalLength() > 0.0;
}

juce::StringArray ResultsPanel::ClipRow::getDragPayload() const
{
    return { file.getFullPathName() };
}

void ResultsPanel::ClipRow::changeListenerCallback (juce::ChangeBroadcaster*)
{
    repaint();
}

void ResultsPanel::ClipRow::timerCallback()
{
    const auto playingThis = player.isPlaying() && player.getCurrentFile() == file;
    const auto wanted = playingThis ? juce::String ("Stop") : juce::String ("Play");

    if (playButton.getButtonText() != wanted)
        playButton.setButtonText (wanted);

    if (playingThis)
        repaint();
}

void ResultsPanel::ClipRow::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds();
    auto waveArea = bounds.withTrimmedLeft (128).reduced (2);

    g.setColour (resultColours::rowFill);
    g.fillRoundedRectangle (waveArea.toFloat(), 3.0f);

    if (thumbnail.getTotalLength() > 0.0)
    {
        g.setColour (resultColours::wave);
        thumbnail.drawChannels (g, waveArea.reduced (2), 0.0, thumbnail.getTotalLength(), 1.0f);

        // Playhead within the clip, so it is obvious which one is sounding.
        if (player.isPlaying() && player.getCurrentFile() == file && player.getLength() > 0.0)
        {
            const auto proportion = juce::jlimit (0.0, 1.0, player.getPosition() / player.getLength());
            const auto x = waveArea.getX() + (int) (proportion * waveArea.getWidth());

            g.setColour (resultColours::text);
            g.drawVerticalLine (x, (float) waveArea.getY(), (float) waveArea.getBottom());
        }
    }
    else
    {
        g.setColour (resultColours::textDim);
        g.setFont (juce::FontOptions (11.0f));
        g.drawText ("loading waveform...", waveArea, juce::Justification::centred);
    }
}

void ResultsPanel::ClipRow::resized()
{
    auto bounds = getLocalBounds();
    nameLabel.setBounds (bounds.removeFromLeft (52).reduced (2));
    playButton.setBounds (bounds.removeFromLeft (70).reduced (2));
}

void ResultsPanel::ClipRow::mouseDrag (const juce::MouseEvent& event)
{
    // One OS drag per gesture. mouseDrag fires on every movement while the button is
    // held, and a small threshold keeps a shaky click from becoming a drag.
    if (dragStarted || event.getDistanceFromDragStart() < 6)
        return;

    if (! file.existsAsFile())
        return;

    dragStarted = true;

    // The only way a VST3 plugin can get audio onto the host's timeline: hand the
    // file to the OS drag service and let the user drop it where they want it.
    juce::DragAndDropContainer::performExternalDragDropOfFiles (getDragPayload(), false, this);
}

void ResultsPanel::ClipRow::mouseUp (const juce::MouseEvent&)
{
    dragStarted = false;
}

//==============================================================================
ResultsPanel::ResultsPanel (GenerationManager& generationToUse,
                            ClipPlayer& playerToUse,
                            juce::AudioProcessor& processorToUse,
                            juce::PropertiesFile* settings)
    : generation (generationToUse),
      player (playerToUse),
      processor (processorToUse),
      cache (settings)
{
    titleLabel.setText ("RESULTS", juce::dontSendNotification);
    titleLabel.setFont (juce::FontOptions (13.0f, juce::Font::bold));
    titleLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    addAndMakeVisible (titleLabel);

    statusLabel.setFont (juce::FontOptions (12.0f));
    statusLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    addAndMakeVisible (statusLabel);

    playheadLabel.setFont (juce::FontOptions (12.0f));
    playheadLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    playheadLabel.setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (playheadLabel);

    historyTitle.setText ("PAST GENERATIONS", juce::dontSendNotification);
    historyTitle.setFont (juce::FontOptions (11.0f, juce::Font::bold));
    historyTitle.setColour (juce::Label::textColourId, resultColours::textDim);
    addAndMakeVisible (historyTitle);

    historyList.setColour (juce::ListBox::backgroundColourId, resultColours::rowFill);
    historyList.setRowHeight (34);
    addAndMakeVisible (historyList);

    deleteButton.onClick = [this] { deleteSelectedEntry(); };
    addAndMakeVisible (deleteButton);

    clearCacheButton.onClick = [this]
    {
        cache.clearAll();
        refreshCache();
    };
    addAndMakeVisible (clearCacheButton);

    cachePathLabel.setText ("Cache", juce::dontSendNotification);
    cachePathLabel.setFont (juce::FontOptions (11.0f));
    cachePathLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    addAndMakeVisible (cachePathLabel);

    cachePathEditor.setColour (juce::TextEditor::backgroundColourId, resultColours::rowFill);
    cachePathEditor.setColour (juce::TextEditor::textColourId, resultColours::text);
    cachePathEditor.setColour (juce::TextEditor::outlineColourId, resultColours::edge);
    cachePathEditor.setFont (juce::FontOptions (11.0f));
    cachePathEditor.setTextToShowWhenEmpty ("default", resultColours::textDim);
    // Committing on focus loss or Enter, not on every keystroke — otherwise a
    // half-typed path would be saved and the browser would flicker through
    // nonexistent directories.
    cachePathEditor.onReturnKey = [this] { commitCachePath(); };
    cachePathEditor.onFocusLost = [this] { commitCachePath(); };
    addAndMakeVisible (cachePathEditor);

    cacheSizeLabel.setFont (juce::FontOptions (11.0f));
    cacheSizeLabel.setColour (juce::Label::textColourId, resultColours::textDim);
    cacheSizeLabel.setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (cacheSizeLabel);

    generation.addChangeListener (this);
    rebuildRows();
    refreshCache();

    // Drives the host playhead readout only.
    startTimerHz (10);
}

ResultsPanel::~ResultsPanel()
{
    stopTimer();
    generation.removeChangeListener (this);
}

void ResultsPanel::changeListenerCallback (juce::ChangeBroadcaster*)
{
    const auto clipsBefore = generation.getClips().size();
    rebuildRows();

    // A finished generation adds a run to the cache, so the browser is stale.
    if (clipsBefore > 0 && generation.getState() == GenerationManager::State::complete)
        refreshCache();
}

//==============================================================================
int ResultsPanel::HistoryModel::getNumRows()
{
    return owner.cacheEntries.size();
}

void ResultsPanel::HistoryModel::paintListBoxItem (int row, juce::Graphics& g,
                                                   int width, int height, bool selected)
{
    if (! juce::isPositiveAndBelow (row, owner.cacheEntries.size()))
        return;

    const auto& entry = owner.cacheEntries.getReference (row);

    if (selected)
    {
        g.setColour (resultColours::edge);
        g.fillRect (0, 0, width, height);
    }

    // A run whose sidecar is missing still lists, so say so rather than leaving a
    // blank line the user cannot interpret.
    const auto prompt = entry.prompt.isNotEmpty() ? entry.prompt
                                                  : juce::String ("(no description recorded)");

    g.setColour (entry.prompt.isNotEmpty() ? resultColours::text : resultColours::textDim);
    g.setFont (juce::FontOptions (12.0f));
    g.drawText (prompt, 6, 2, width - 12, height / 2, juce::Justification::centredLeft, true);

    juce::StringArray details;
    details.add (entry.created.formatted ("%d %b %H:%M"));

    if (entry.durationSeconds > 0.0)
        details.add (juce::String ((int) entry.durationSeconds) + "s");

    details.add (juce::String (entry.clips.size())
                     + (entry.clips.size() == 1 ? " clip" : " clips"));
    details.add (juce::File::descriptionOfSizeInBytes (entry.sizeInBytes));

    g.setColour (resultColours::textDim);
    g.setFont (juce::FontOptions (10.5f));
    g.drawText (details.joinIntoString ("  -  "), 6, height / 2, width - 12, height / 2,
                juce::Justification::centredLeft, true);
}

void ResultsPanel::HistoryModel::listBoxItemDoubleClicked (int row, const juce::MouseEvent&)
{
    if (! juce::isPositiveAndBelow (row, owner.cacheEntries.size()))
        return;

    // Double-click previews the first clip of a past generation.
    const auto& entry = owner.cacheEntries.getReference (row);

    if (! entry.clips.isEmpty())
        owner.player.toggle (entry.clips.getFirst());
}

void ResultsPanel::commitCachePath()
{
    const auto typed = cachePathEditor.getText().trim();
    const auto wanted = typed.isEmpty() ? juce::File() : juce::File (typed);

    if (wanted.getFullPathName() == cache.getDirectory().getFullPathName())
        return;

    cache.setDirectory (wanted);
    refreshCache();
}

void ResultsPanel::refreshCache()
{
    cacheEntries = cache.listEntries();

    if (! cachePathEditor.hasKeyboardFocus (true))
        cachePathEditor.setText (cache.getDirectory().getFullPathName(), false);

    historyList.updateContent();
    historyList.repaint();

    juce::String reason;

    if (cache.hasProblem (reason))
    {
        cacheSizeLabel.setText (reason, juce::dontSendNotification);
    }
    else
    {
        cacheSizeLabel.setText (juce::String (cacheEntries.size())
                                    + (cacheEntries.size() == 1 ? " generation - " : " generations - ")
                                    + cache.getTotalSizeDescription(),
                                juce::dontSendNotification);
    }

    deleteButton.setEnabled (historyList.getSelectedRow() >= 0);
    clearCacheButton.setEnabled (! cacheEntries.isEmpty());
}

bool ResultsPanel::deleteSelectedEntry()
{
    const auto row = historyList.getSelectedRow();

    if (! juce::isPositiveAndBelow (row, cacheEntries.size()))
        return false;

    // Stop first: deleting the file underneath a playing clip is a bad time.
    const auto& entry = cacheEntries.getReference (row);

    if (entry.clips.contains (player.getCurrentFile()))
        player.stop();

    const auto deleted = cache.deleteEntry (entry);
    refreshCache();
    historyList.deselectAllRows();
    deleteButton.setEnabled (false);

    return deleted;
}

void ResultsPanel::timerCallback()
{
    juce::String text { "Host playhead: --" };

    if (auto* playHead = processor.getPlayHead())
    {
        if (const auto position = playHead->getPosition())
        {
            if (const auto seconds = position->getTimeInSeconds())
            {
                const auto total = (int) *seconds;
                text = "Host playhead: "
                     + juce::String (total / 60) + ":"
                     + juce::String (total % 60).paddedLeft ('0', 2) + "."
                     + juce::String ((int) ((*seconds - (double) total) * 1000.0)).paddedLeft ('0', 3);
            }
        }
    }

    if (playheadLabel.getText() != text)
        playheadLabel.setText (text, juce::dontSendNotification);
}

void ResultsPanel::rebuildRows()
{
    const auto& clips = generation.getClips();

    // Only rebuild when the set actually changed — the manager broadcasts on every
    // state transition, and tearing down rows would restart the waveform loads.
    auto sameAsShown = clips.size() == clipRows.size();

    if (sameAsShown)
    {
        for (int i = 0; i < clips.size(); ++i)
        {
            if (clipRows[i]->getFile() != clips[i])
            {
                sameAsShown = false;
                break;
            }
        }
    }

    if (! sameAsShown)
    {
        clipRows.clear();

        for (int i = 0; i < clips.size(); ++i)
        {
            auto* row = clipRows.add (new ClipRow (clips[i], player, player.getFormatManager(),
                                                   thumbnailCache, i));
            addAndMakeVisible (row);

            if (! history.contains (clips[i]))
                history.add (clips[i]);
        }

        resized();
    }

    if (clips.isEmpty())
    {
        statusLabel.setText (generation.getState() == GenerationManager::State::idle
                                 ? "Generated clips will appear here"
                                 : generation.getStatusMessage(),
                             juce::dontSendNotification);
    }
    else
    {
        statusLabel.setText (juce::String (clips.size())
                                 + (clips.size() == 1 ? " clip - drag it onto a track"
                                                      : " clips - drag one onto a track"),
                             juce::dontSendNotification);
    }
}

void ResultsPanel::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat();

    g.setColour (resultColours::fill);
    g.fillRoundedRectangle (bounds, 6.0f);

    g.setColour (resultColours::edge);
    g.drawRoundedRectangle (bounds.reduced (0.5f), 6.0f, 1.0f);
}

void ResultsPanel::resized()
{
    auto area = getLocalBounds().reduced (12, 8);

    auto header = area.removeFromTop (18);
    titleLabel.setBounds (header.removeFromLeft (90));
    playheadLabel.setBounds (header);

    area.removeFromTop (4);

    auto footer = area.removeFromBottom (18);
    statusLabel.setBounds (footer);
    area.removeFromBottom (6);

    // Cache browser occupies the lower half; the current generation's rows keep the
    // top so the newest result is what you see first.
    auto browser = area.removeFromBottom (juce::jmax (0, area.getHeight() / 2));

    if (browser.getHeight() > 40)
    {
        auto browserHeader = browser.removeFromTop (16);
        historyTitle.setBounds (browserHeader.removeFromLeft (140));
        cacheSizeLabel.setBounds (browserHeader);

        auto pathRow = browser.removeFromTop (20);
        cachePathLabel.setBounds (pathRow.removeFromLeft (44));
        cachePathEditor.setBounds (pathRow.reduced (0, 1));
        browser.removeFromTop (4);

        auto browserFooter = browser.removeFromBottom (22);
        deleteButton.setBounds (browserFooter.removeFromLeft (80).reduced (0, 1));
        browserFooter.removeFromLeft (6);
        clearCacheButton.setBounds (browserFooter.removeFromLeft (100).reduced (0, 1));

        browser.removeFromBottom (4);
        historyList.setBounds (browser);
    }
    else
    {
        historyTitle.setBounds ({});
        cacheSizeLabel.setBounds ({});
        deleteButton.setBounds ({});
        clearCacheButton.setBounds ({});
        historyList.setBounds ({});
    }

    area.removeFromBottom (6);

    for (auto* row : clipRows)
    {
        if (area.getHeight() <= 0)
            break;

        row->setBounds (area.removeFromTop (juce::jmin (44, area.getHeight())));
        area.removeFromTop (4);
    }
}

} // namespace acemusic
