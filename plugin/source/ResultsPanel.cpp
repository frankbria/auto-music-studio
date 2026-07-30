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
                            juce::AudioProcessor& processorToUse)
    : generation (generationToUse),
      player (playerToUse),
      processor (processorToUse)
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

    generation.addChangeListener (this);
    rebuildRows();

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
    rebuildRows();
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
    area.removeFromBottom (4);

    for (auto* row : clipRows)
    {
        if (area.getHeight() <= 0)
            break;

        row->setBounds (area.removeFromTop (juce::jmin (44, area.getHeight())));
        area.removeFromTop (4);
    }
}

} // namespace acemusic
