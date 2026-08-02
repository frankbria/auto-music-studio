#include "GenerationPanel.h"

namespace acemusic
{

namespace genColours
{
    static const juce::Colour fill    { 0xff1d1d20 };
    static const juce::Colour edge    { 0xff34343a };
    static const juce::Colour text    { 0xffe9e9ec };
    static const juce::Colour textDim { 0xff8b8b93 };
    static const juce::Colour field   { 0xff121214 };
}

namespace
{
    /** "Auto"/"Any"/"Random" all mean "let the server choose", and each control shows
        that as placeholder text rather than a magic value the user could mistype. */
    constexpr const char* autoPlaceholder   = "Auto";
    constexpr const char* randomPlaceholder = "Random";

    void styleEditor (juce::TextEditor& editor, const juce::String& placeholder)
    {
        editor.setColour (juce::TextEditor::backgroundColourId, genColours::field);
        editor.setColour (juce::TextEditor::textColourId, genColours::text);
        editor.setColour (juce::TextEditor::outlineColourId, genColours::edge);
        editor.setFont (juce::FontOptions (13.0f));

        if (placeholder.isNotEmpty())
            editor.setTextToShowWhenEmpty (placeholder, genColours::textDim);
    }

    void styleCombo (juce::ComboBox& box)
    {
        box.setColour (juce::ComboBox::backgroundColourId, genColours::field);
        box.setColour (juce::ComboBox::textColourId, genColours::text);
        box.setColour (juce::ComboBox::outlineColourId, genColours::edge);
    }

    void styleCaption (juce::Label& label, const juce::String& text)
    {
        label.setText (text, juce::dontSendNotification);
        label.setFont (juce::FontOptions (12.0f));
        label.setColour (juce::Label::textColourId, genColours::textDim);
    }
}

//==============================================================================
GenerationPanel::GenerationPanel (GenerationManager& generationToUse,
                                  ConnectionManager& connectionToUse,
                                  HostSync* hostSyncToUse)
    : generation (generationToUse),
      connection (connectionToUse),
      hostSync (hostSyncToUse)
{
    titleLabel.setText ("GENERATION", juce::dontSendNotification);
    titleLabel.setFont (juce::FontOptions (13.0f, juce::Font::bold));
    titleLabel.setColour (juce::Label::textColourId, genColours::textDim);
    addAndMakeVisible (titleLabel);

    styleCaption (promptLabel, "Prompt");
    addAndMakeVisible (promptLabel);
    promptEditor.setMultiLine (true, true);
    promptEditor.setReturnKeyStartsNewLine (true);
    styleEditor (promptEditor, "Describe the music you want");
    // Generate's availability depends on the prompt, so typing has to re-evaluate it
    // — otherwise the button sits dead until some unrelated event repaints the panel.
    promptEditor.onTextChange = [this] { refresh(); };
    addAndMakeVisible (promptEditor);

    // Lyrics are collapsible because most generations do not use them, and an always
    // -on multi-line box would dominate a panel this size.
    lyricsToggle.setColour (juce::ToggleButton::textColourId, genColours::textDim);
    lyricsToggle.onClick = [this]
    {
        lyricsEditor.setVisible (lyricsToggle.getToggleState());
        resized();
    };
    addAndMakeVisible (lyricsToggle);

    lyricsEditor.setMultiLine (true, true);
    lyricsEditor.setReturnKeyStartsNewLine (true);
    styleEditor (lyricsEditor, "[Verse]\nYour words here");
    lyricsEditor.setVisible (false);
    addChildComponent (lyricsEditor);

    styleCaption (languageLabel, "Language");
    addAndMakeVisible (languageLabel);
    styleCombo (languageSelector);
    languageSelector.addItem ("Auto", 1);
    {
        const auto languages = GenerationRequest::vocalLanguages();

        for (int i = 0; i < languages.size(); ++i)
            languageSelector.addItem (languages[i], i + 2);
    }
    languageSelector.setSelectedId (1, juce::dontSendNotification);
    addAndMakeVisible (languageSelector);

    instrumentalToggle.setColour (juce::ToggleButton::textColourId, genColours::textDim);
    addAndMakeVisible (instrumentalToggle);

    styleCaption (bpmLabel, "BPM");
    addAndMakeVisible (bpmLabel);
    styleEditor (bpmEditor, autoPlaceholder);
    bpmEditor.setInputRestrictions (3, "0123456789");
    // The one rule for host tempo sync: the field follows the host until the user
    // types in it, and follows it again the moment they clear it. Sync writes with
    // setText(..., false), which does not fire this, so the panel cannot cancel its
    // own sync by obeying the host.
    bpmEditor.onTextChange = [this]
    {
        bpmSynced = bpmEditor.getText().trim().isEmpty();
        refresh();
    };
    addAndMakeVisible (bpmEditor);

    styleCaption (keyLabel, "Key");
    addAndMakeVisible (keyLabel);
    styleCombo (keySelector);
    {
        const auto keys = GenerationRequest::musicalKeys();

        for (int i = 0; i < keys.size(); ++i)
            keySelector.addItem (keys[i], i + 1);
    }
    keySelector.setSelectedId (1, juce::dontSendNotification);
    addAndMakeVisible (keySelector);

    styleCaption (durationLabel, "Duration (s)");
    addAndMakeVisible (durationLabel);
    styleEditor (durationEditor, "60");
    durationEditor.setInputRestrictions (4, "0123456789");
    durationEditor.setText ("60", false);
    durationEditor.onTextChange = [this]
    {
        // Same rule as the BPM field (US-24.1): the host drives it until the user
        // types, and clearing hands it back. Auto-applied writes use
        // setText(..., false), which does not land here.
        durationSynced = durationEditor.getText().trim().isEmpty();
        refresh();
    };
    addAndMakeVisible (durationEditor);

    styleCaption (seedLabel, "Seed");
    addAndMakeVisible (seedLabel);
    styleEditor (seedEditor, randomPlaceholder);
    seedEditor.setInputRestrictions (10, "0123456789");
    addAndMakeVisible (seedEditor);

    styleCaption (qualityLabel, "Quality");
    addAndMakeVisible (qualityLabel);
    styleCombo (qualitySelector);
    {
        const auto qualities = GenerationRequest::allQualities();

        for (int i = 0; i < qualities.size(); ++i)
            qualitySelector.addItem (GenerationRequest::toString (qualities[i]), i + 1);
    }
    qualitySelector.setSelectedId (2, juce::dontSendNotification);   // Standard
    addAndMakeVisible (qualitySelector);

    styleCaption (modeLabel, "Mode");
    addAndMakeVisible (modeLabel);
    styleCombo (modeSelector);
    modeSelector.addItem (GenerationRequest::toString (GenerationRequest::Mode::textToMusic), 1);
    modeSelector.addItem (GenerationRequest::toString (GenerationRequest::Mode::cover), 2);
    modeSelector.setSelectedId (1, juce::dontSendNotification);
    modeSelector.onChange = [this] { refresh(); };
    addAndMakeVisible (modeSelector);

    generateButton.onClick = [this] { generation.start (buildRequest()); };
    addAndMakeVisible (generateButton);

    cancelButton.onClick = [this] { generation.cancel(); };
    addAndMakeVisible (cancelButton);

    statusLabel.setFont (juce::FontOptions (12.0f));
    statusLabel.setColour (juce::Label::textColourId, genColours::textDim);
    addAndMakeVisible (statusLabel);

    progressBar.setColour (juce::ProgressBar::backgroundColourId, genColours::field);
    addChildComponent (progressBar);

    syncLabel.setFont (juce::FontOptions (12.0f));
    syncLabel.setColour (juce::Label::textColourId, genColours::textDim);
    syncLabel.setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (syncLabel);

    selectionLabel.setFont (juce::FontOptions (12.0f));
    selectionLabel.setColour (juce::Label::textColourId, genColours::textDim);
    addAndMakeVisible (selectionLabel);

    generation.addChangeListener (this);
    connection.addChangeListener (this);

    // Fill the BPM field before the first paint, so opening the plugin in a project
    // that is already running shows the host tempo rather than a blank field that
    // fills in half a second later.
    applyHostTempo();
    applyHostSelection();
    refresh();

    // Ticks the elapsed-time readout and follows the host tempo. Everything else the
    // panel shows arrives as a change message.
    startTimerHz (2);
}

GenerationPanel::~GenerationPanel()
{
    stopTimer();
    generation.removeChangeListener (this);
    connection.removeChangeListener (this);
}

void GenerationPanel::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat();

    g.setColour (genColours::fill);
    g.fillRoundedRectangle (bounds, 6.0f);

    g.setColour (genColours::edge);
    g.drawRoundedRectangle (bounds.reduced (0.5f), 6.0f, 1.0f);
}

void GenerationPanel::resized()
{
    auto area = getLocalBounds().reduced (12, 8);

    titleLabel.setBounds (area.removeFromTop (18));
    area.removeFromTop (4);

    // Bottom-up: pin the action row and status, then let the prompt take the slack.
    auto actions = area.removeFromBottom (26);
    generateButton.setBounds (actions.removeFromLeft (110));
    actions.removeFromLeft (8);
    cancelButton.setBounds (actions.removeFromLeft (80));
    actions.removeFromLeft (10);
    progressBar.setBounds (actions.removeFromLeft (juce::jmin (140, actions.getWidth() / 2)));
    actions.removeFromLeft (8);
    statusLabel.setBounds (actions);

    area.removeFromBottom (8);

    // Parameter row: two lines of label-over-control.
    auto paramsRow = area.removeFromBottom (40);
    const auto cellWidth = paramsRow.getWidth() / 6;

    auto placeCell = [&paramsRow, cellWidth] (juce::Label& label, juce::Component& control)
    {
        auto cell = paramsRow.removeFromLeft (cellWidth).reduced (3, 0);
        label.setBounds (cell.removeFromTop (14));
        control.setBounds (cell);
    };

    placeCell (bpmLabel, bpmEditor);
    placeCell (keyLabel, keySelector);
    placeCell (durationLabel, durationEditor);
    placeCell (seedLabel, seedEditor);
    placeCell (qualityLabel, qualitySelector);
    placeCell (modeLabel, modeSelector);

    area.removeFromBottom (8);

    auto languageRow = area.removeFromBottom (24);
    languageLabel.setBounds (languageRow.removeFromLeft (70));
    languageSelector.setBounds (languageRow.removeFromLeft (180));
    languageRow.removeFromLeft (12);
    instrumentalToggle.setBounds (languageRow.removeFromLeft (120));
    lyricsToggle.setBounds (languageRow.removeFromLeft (90));
    // Sync indicator right-aligned, selection readout taking what is left beside it.
    syncLabel.setBounds (languageRow.removeFromRight (juce::jmin (170, languageRow.getWidth() / 2)));
    selectionLabel.setBounds (languageRow);

    area.removeFromBottom (8);

    if (lyricsEditor.isVisible())
    {
        lyricsEditor.setBounds (area.removeFromBottom (juce::jmax (44, area.getHeight() / 2)));
        area.removeFromBottom (8);
    }

    promptLabel.setBounds (area.removeFromTop (14));
    promptEditor.setBounds (area);
}

void GenerationPanel::changeListenerCallback (juce::ChangeBroadcaster*)
{
    refresh();
}

void GenerationPanel::timerCallback()
{
    // Unconditional now, not just while busy: this is also what tracks a tempo change
    // made in the DAW while the panel sits idle. refresh() is a handful of setters that
    // no-op when nothing moved, so 2Hz costs nothing.
    applyHostTempo();
    applyHostSelection();
    refresh();
}

bool GenerationPanel::applyHostTempo()
{
    if (hostSync == nullptr || ! bpmSynced)
        return false;

    // Never rewrite the field out from under someone typing in it. TextEditor delivers
    // onTextChange asynchronously (it posts a command message), so between the first
    // keystroke and the callback that clears bpmSynced there is a window where this
    // would otherwise overwrite what they just typed.
    if (bpmEditor.hasKeyboardFocus (false))
        return false;

    const auto snapshot = hostSync->get();

    if (! snapshot.hasBpm())
        return false;

    const auto wanted = juce::String (juce::roundToInt (snapshot.bpm));

    if (bpmEditor.getText() == wanted)
        return false;

    bpmEditor.setText (wanted, false);
    return true;
}

bool GenerationPanel::applyHostSelection()
{
    if (hostSync == nullptr || ! durationSynced)
        return false;

    // Same reason as applyHostTempo: never rewrite a field being typed into.
    if (durationEditor.hasKeyboardFocus (false))
        return false;

    const auto selection = HostSync::describeSelection (hostSync->get());

    // No selection, or one whose length is unknowable, leaves the field exactly as
    // Stage 23 left it. Nothing is invented from a range with no tempo behind it.
    if (! selection.present || ! selection.hasLength)
        return false;

    const auto seconds = juce::roundToInt (selection.lengthSeconds);

    if (seconds <= 0)
        return false;

    const auto wanted = juce::String (seconds);

    if (durationEditor.getText() == wanted)
        return false;

    durationEditor.setText (wanted, false);
    return true;
}

juce::String GenerationPanel::getSelectionText() const
{
    const auto selection = hostSync != nullptr
                             ? HostSync::describeSelection (hostSync->get())
                             : HostSync::Selection{};

    if (! selection.present)
        return "Selection: none";

    juce::String text { "Selection: " };

    if (selection.hasBars)
    {
        text << "bars " << HostSync::formatBar (selection.startBar)
             << "-" << HostSync::formatBar (selection.endBar);
    }

    if (selection.hasLength)
    {
        if (selection.hasBars)
            text << ", ";

        text << juce::String (selection.lengthSeconds, 1) << "s";
    }
    else
    {
        // A range with no tempo behind it: say so rather than show "0.0s".
        text << (selection.hasBars ? " (no host tempo)" : "set, but no host tempo");
    }

    return text;
}

juce::String GenerationPanel::getSyncStatusText() const
{
    if (! bpmSynced)
        return "Sync: off (manual BPM)";

    const auto snapshot = hostSync != nullptr ? hostSync->get() : HostSync::Snapshot{};

    if (! snapshot.hasBpm())
        return "Sync: no host tempo";

    return "Sync: host " + juce::String (juce::roundToInt (snapshot.bpm)) + " BPM";
}

GenerationRequest GenerationPanel::buildRequest() const
{
    GenerationRequest request;

    request.prompt = promptEditor.getText();

    if (lyricsToggle.getToggleState())
        request.lyrics = lyricsEditor.getText();

    // Item 1 is "Auto" in both of these, which means "omit".
    if (languageSelector.getSelectedId() > 1)
        request.vocalLanguage = languageSelector.getText();

    request.instrumental = instrumentalToggle.getToggleState();

    const auto bpmText = bpmEditor.getText().trim();
    request.bpm = bpmText.isEmpty() ? -1 : bpmText.getIntValue();

    if (keySelector.getSelectedId() > 1)
        request.key = keySelector.getText();

    const auto durationText = durationEditor.getText().trim();
    request.durationSeconds = durationText.isEmpty() ? 60 : durationText.getIntValue();

    const auto seedText = seedEditor.getText().trim();
    request.seed = seedText.isEmpty() ? -1 : seedText.getLargeIntValue();

    const auto qualities = GenerationRequest::allQualities();
    const auto qualityIndex = juce::jlimit (0, qualities.size() - 1, qualitySelector.getSelectedId() - 1);
    request.quality = qualities[qualityIndex];

    request.mode = modeSelector.getSelectedId() == 2 ? GenerationRequest::Mode::cover
                                                     : GenerationRequest::Mode::textToMusic;

    return request;
}

void GenerationPanel::applyRequest (const GenerationRequest& request)
{
    promptEditor.setText (request.prompt, false);

    lyricsToggle.setToggleState (request.lyrics.isNotEmpty(), juce::dontSendNotification);
    lyricsEditor.setText (request.lyrics, false);
    lyricsEditor.setVisible (lyricsToggle.getToggleState());

    const auto languages = GenerationRequest::vocalLanguages();
    const auto languageIndex = languages.indexOf (request.vocalLanguage);
    languageSelector.setSelectedId (languageIndex >= 0 ? languageIndex + 2 : 1, juce::dontSendNotification);

    instrumentalToggle.setToggleState (request.instrumental, juce::dontSendNotification);

    // An applied request carries the user's own BPM, so it takes the field off sync —
    // except when it leaves BPM on Auto, which hands it back.
    bpmSynced = request.bpm <= 0;
    bpmEditor.setText (request.bpm > 0 ? juce::String (request.bpm) : juce::String(), false);

    const auto keyIndex = GenerationRequest::musicalKeys().indexOf (request.key);
    keySelector.setSelectedId (keyIndex >= 0 ? keyIndex + 1 : 1, juce::dontSendNotification);

    // As with BPM: a recalled request carries its own duration, so it stops tracking.
    durationSynced = false;
    durationEditor.setText (juce::String (request.durationSeconds), false);
    seedEditor.setText (request.seed >= 0 ? juce::String (request.seed) : juce::String(), false);

    qualitySelector.setSelectedId (GenerationRequest::allQualities().indexOf (request.quality) + 1,
                                   juce::dontSendNotification);
    modeSelector.setSelectedId (request.mode == GenerationRequest::Mode::cover ? 2 : 1,
                                juce::dontSendNotification);

    resized();
}

void GenerationPanel::refresh()
{
    const auto busy = generation.isBusy();

    // AC: generation is unavailable while the connection is not green. Ask the
    // manager rather than re-deriving the rule here, so there is one answer.
    const auto problem = generation.findStartProblem (buildRequest());

    generateButton.setEnabled (! busy && problem.isEmpty());
    cancelButton.setEnabled (busy);

    progressBar.setVisible (busy);

    const auto syncText = getSyncStatusText();

    if (syncLabel.getText() != syncText)
        syncLabel.setText (syncText, juce::dontSendNotification);

    const auto selectionText = getSelectionText();

    if (selectionLabel.getText() != selectionText)
        selectionLabel.setText (selectionText, juce::dontSendNotification);

    for (auto* control : std::initializer_list<juce::Component*> {
             &promptEditor, &lyricsEditor, &lyricsToggle, &languageSelector, &instrumentalToggle,
             &bpmEditor, &keySelector, &durationEditor, &seedEditor, &qualitySelector, &modeSelector })
    {
        control->setEnabled (! busy);
    }

    if (busy)
    {
        statusLabel.setText (generation.getStatusMessage()
                                 + "  " + juce::String (generation.getElapsedSeconds()) + "s",
                             juce::dontSendNotification);
    }
    else if (generation.getState() == GenerationManager::State::idle && problem.isNotEmpty())
    {
        // Say why Generate is unavailable rather than leaving a dead button.
        statusLabel.setText (problem, juce::dontSendNotification);
    }
    else
    {
        statusLabel.setText (generation.getStatusMessage(), juce::dontSendNotification);
    }
}

} // namespace acemusic
