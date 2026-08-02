#pragma once

#include "GenerationManager.h"
#include "HostSync.h"
#include "LegoStack.h"
#include "MidiCapture.h"
#include "SidechainCapture.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    The generation controls: prompt, lyrics, and the parameter row, plus Generate /
    Cancel and a progress line.

    Holds no generation state of its own — it reads GenerationManager and pushes edits
    back, so closing and reopening the plugin window shows whatever the run is actually
    doing rather than an idle panel.
*/
class GenerationPanel final : public juce::Component,
                              private juce::ChangeListener,
                              private juce::Timer
{
public:
    /** @param hostSyncToUse  the host transport, or null for "there is no host" —
                              which is what a test that does not care about tempo
                              sync gets, and what the panel shows as no host tempo. */
    GenerationPanel (GenerationManager&,
                     ConnectionManager&,
                     HostSync* hostSyncToUse = nullptr,
                     MidiCapture* midiCaptureToUse = nullptr,
                     SidechainCapture* sidechainCaptureToUse = nullptr,
                     bool hostOffersSidechain = false);
    ~GenerationPanel() override;

    void paint (juce::Graphics&) override;
    void resized() override;

    /** The request the controls currently describe. */
    GenerationRequest buildRequest() const;

    /** Fills the controls from `request`. Used by tests and, later, by presets. */
    void applyRequest (const GenerationRequest&);

    //==============================================================================
    // Test seams — the widgets the acceptance criteria talk about.
    juce::TextEditor&   getPromptEditor() noexcept        { return promptEditor; }
    juce::TextEditor&   getLyricsEditor() noexcept        { return lyricsEditor; }
    juce::ToggleButton& getLyricsToggle() noexcept        { return lyricsToggle; }
    juce::ComboBox&     getLanguageSelector() noexcept    { return languageSelector; }
    juce::ToggleButton& getInstrumentalToggle() noexcept  { return instrumentalToggle; }
    juce::TextEditor&   getBpmEditor() noexcept           { return bpmEditor; }
    juce::ComboBox&     getKeySelector() noexcept         { return keySelector; }
    juce::TextEditor&   getDurationEditor() noexcept      { return durationEditor; }
    juce::TextEditor&   getSeedEditor() noexcept          { return seedEditor; }
    juce::ComboBox&     getQualitySelector() noexcept     { return qualitySelector; }
    juce::ComboBox&     getModeSelector() noexcept        { return modeSelector; }
    juce::TextButton&   getGenerateButton() noexcept      { return generateButton; }
    juce::TextButton&   getCancelButton() noexcept        { return cancelButton; }
    juce::Label&        getStatusLabel() noexcept         { return statusLabel; }
    juce::Label&        getSyncLabel() noexcept           { return syncLabel; }
    juce::Label&        getSelectionLabel() noexcept      { return selectionLabel; }
    juce::ToggleButton& getMidiRecordToggle() noexcept     { return midiRecordToggle; }
    juce::ToggleButton& getSidechainRecordToggle() noexcept { return sidechainRecordToggle; }
    juce::Label&        getCaptureLabel() noexcept         { return captureLabel; }
    juce::ComboBox&     getLegoTrackSelector() noexcept    { return legoTrackSelector; }
    juce::Label&        getLegoLabel() noexcept            { return legoLabel; }

    /** The layers built so far in Lego mode. */
    LegoStack& getLegoStack() noexcept                    { return legoStack; }

    /** Records a finished generation as the next layer. Called when a Lego generation
        completes; exposed so a test does not have to drive a whole server round trip. */
    void addLegoLayer (const juce::File& clip);

    /** As above, with the track and prompt the run was started with rather than whatever
        the controls read now. */
    void addLegoLayer (const juce::File& clip, const juce::String& track, const juce::String& prompt);

    /** True when `mode` has the input it needs and can be chosen. */
    bool isModeAvailable (GenerationRequest::Mode) const;
    juce::ProgressBar&  getProgressBar() noexcept         { return progressBar; }

    /** True while the BPM field is following the host rather than the user. */
    bool isBpmSynced() const noexcept                     { return bpmSynced; }

    /** True while the duration field is following the host's loop range. */
    bool isDurationSynced() const noexcept                { return durationSynced; }

private:
    void changeListenerCallback (juce::ChangeBroadcaster*) override;
    void timerCallback() override;
    void refresh();

    /** The host's transport, or an empty snapshot when there is no host. */
    HostSync::Snapshot getHostSnapshot() const;

    /** Copies the host tempo into the BPM field when the field is still following it.
        @returns true if the field changed. */
    bool applyHostTempo();

    /** Copies the host's loop-range length into the duration field when that field is
        still following it. @returns true if the field changed. */
    bool applyHostSelection();

    /** What the sync indicator should read right now. */
    juce::String getSyncStatusText() const;

    /** What the selection readout should read right now. */
    juce::String getSelectionText() const;

    /** What the capture indicator should read right now. */
    juce::String getCaptureText() const;

    /** What the Lego readout should read right now. */
    juce::String getLegoText() const;

    /** Adds the clip of a just-finished Lego run to the stack. Idempotent. */
    void collectFinishedLegoLayer();

    /** Writes the layers-so-far mix and points `request` at it. Does nothing for the
        first layer, which has no context. */
    void attachLegoContext (GenerationRequest&) const;

    /** Greys out the modes whose input has not been captured. */
    void refreshModeAvailability();

    /** Where the layers-so-far mix is written for a Lego generation. */
    juce::File getLegoContextFile() const;

    /** Where the capture backing `mode` is written. Known before the write happens, so
        buildRequest can name it and validation can pass. */
    juce::File getCaptureFileFor (GenerationRequest::Mode) const;

    /** Whether `mode`'s input has actually been captured. */
    bool hasCaptureFor (GenerationRequest::Mode) const;

    /** Writes the capture a non-text mode needs and points `request` at it.
        @returns false when the mode's input is missing or could not be written. */
    bool attachSourceAudio (GenerationRequest&) const;

    GenerationManager& generation;
    ConnectionManager& connection;
    HostSync* hostSync = nullptr;
    MidiCapture* midiCapture = nullptr;
    SidechainCapture* sidechainCapture = nullptr;

    /** Whether the host actually gave the plugin a sidechain bus. Without one, Cover and
        Repaint can never be satisfied and say so rather than sitting there enabled. */
    bool hostOffersSidechain = false;

    /** False once the user has typed their own BPM. Clearing the field back to the
        "Auto" placeholder sets it true again, which is how sync is resumed — the
        panel already treats an empty field as "let something else choose". */
    bool bpmSynced = true;

    /** Same rule as bpmSynced, for the duration field and the host's loop range. False
        once the user types their own duration; clearing the field resumes tracking. */
    bool durationSynced = true;

    juce::Label      titleLabel;

    juce::Label      promptLabel;
    juce::TextEditor promptEditor;

    juce::ToggleButton lyricsToggle { "Lyrics" };
    juce::TextEditor   lyricsEditor;

    juce::Label      languageLabel;
    juce::ComboBox   languageSelector;
    juce::ToggleButton instrumentalToggle { "Instrumental" };

    juce::Label      bpmLabel;
    juce::TextEditor bpmEditor;
    juce::Label      keyLabel;
    juce::ComboBox   keySelector;
    juce::Label      durationLabel;
    juce::TextEditor durationEditor;
    juce::Label      seedLabel;
    juce::TextEditor seedEditor;
    juce::Label      qualityLabel;
    juce::ComboBox   qualitySelector;
    juce::Label      modeLabel;
    juce::ComboBox   modeSelector;

    juce::TextButton generateButton { "Generate" };
    juce::TextButton cancelButton { "Cancel" };
    juce::Label      statusLabel;
    juce::Label      syncLabel;
    juce::Label      selectionLabel;

    LegoStack legoStack;

    /** Which layer a Generate would replace, or < 0 to append a new one. */
    int legoRegenerateIndex = -1;

    /** Set when a Lego generation is in flight, with the track and prompt it was started
        with — the controls may have moved on by the time it lands. */
    bool legoRunPending = false;
    juce::String pendingLegoTrack;
    juce::String pendingLegoPrompt;

    juce::Label      legoTrackLabel;
    juce::ComboBox   legoTrackSelector;
    juce::Label      legoLabel;

    juce::ToggleButton midiRecordToggle { "Record MIDI" };
    juce::ToggleButton sidechainRecordToggle { "Capture sidechain" };
    juce::Label        captureLabel;

    /** The server reports no percentage, so this runs in indeterminate mode while a
        job is in flight. See the progress note in the README. */
    double progress = -1.0;
    juce::ProgressBar progressBar { progress };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (GenerationPanel)
};

} // namespace acemusic
