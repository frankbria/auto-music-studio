#pragma once

#include "GenerationManager.h"

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
    GenerationPanel (GenerationManager&, ConnectionManager&);
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
    juce::ProgressBar&  getProgressBar() noexcept         { return progressBar; }

private:
    void changeListenerCallback (juce::ChangeBroadcaster*) override;
    void timerCallback() override;
    void refresh();

    GenerationManager& generation;
    ConnectionManager& connection;

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

    /** The server reports no percentage, so this runs in indeterminate mode while a
        job is in flight. See the progress note in the README. */
    double progress = -1.0;
    juce::ProgressBar progressBar { progress };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (GenerationPanel)
};

} // namespace acemusic
