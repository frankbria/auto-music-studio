#include "PlatformPanel.h"

namespace acemusic
{

namespace platformColours
{
    static const juce::Colour fill    { 0xff1d1d20 };
    static const juce::Colour edge    { 0xff34343a };
    static const juce::Colour text    { 0xffe9e9ec };
    static const juce::Colour textDim { 0xff8b8b93 };
    static const juce::Colour field   { 0xff121214 };
    static const juce::Colour bad     { 0xffe0574a };
}

namespace
{
    void styleEditor (juce::TextEditor& editor, const juce::String& placeholder)
    {
        editor.setColour (juce::TextEditor::backgroundColourId, platformColours::field);
        editor.setColour (juce::TextEditor::textColourId, platformColours::text);
        editor.setColour (juce::TextEditor::outlineColourId, platformColours::edge);
        editor.setFont (juce::FontOptions (13.0f));

        if (placeholder.isNotEmpty())
            editor.setTextToShowWhenEmpty (placeholder, platformColours::textDim);
    }

    void styleCaption (juce::Label& label, const juce::String& text)
    {
        label.setText (text, juce::dontSendNotification);
        label.setFont (juce::FontOptions (12.0f));
        label.setColour (juce::Label::textColourId, platformColours::textDim);
    }
}

//==============================================================================
int PlatformPanel::ClipListModel::getNumRows()
{
    return owner.clips.size();
}

void PlatformPanel::ClipListModel::paintListBoxItem (int row, juce::Graphics& g,
                                                     int width, int height, bool selected)
{
    if (! juce::isPositiveAndBelow (row, owner.clips.size()))
        return;

    const auto& clip = owner.clips.getReference (row);

    if (selected)
    {
        g.setColour (platformColours::edge);
        g.fillRect (0, 0, width, height);
    }

    g.setColour (platformColours::text);
    g.setFont (juce::FontOptions (13.0f));
    g.drawText (clip.title.isNotEmpty() ? clip.title : juce::String ("Untitled"),
                6, 0, width - 150, height, juce::Justification::centredLeft, true);

    juce::StringArray details;

    if (clip.bpm > 0)
        details.add (juce::String (clip.bpm) + " BPM");

    if (clip.key.isNotEmpty())
        details.add (clip.key);

    if (clip.duration > 0.0)
        details.add (juce::String ((int) clip.duration) + "s");

    g.setColour (platformColours::textDim);
    g.setFont (juce::FontOptions (12.0f));
    g.drawText (details.joinIntoString ("  "), width - 146, 0, 140, height,
                juce::Justification::centredRight, true);
}

void PlatformPanel::ClipListModel::selectedRowsChanged (int)
{
    owner.refresh();
}

//==============================================================================
PlatformPanel::PlatformPanel (BackgroundTaskQueue& queueToUse,
                              GenerationManager& generationToUse,
                              juce::PropertiesFile* settingsToUse)
    : queue (queueToUse),
      generation (generationToUse),
      settings (settingsToUse)
{
    titleLabel.setText ("PLATFORM", juce::dontSendNotification);
    titleLabel.setFont (juce::FontOptions (13.0f, juce::Font::bold));
    titleLabel.setColour (juce::Label::textColourId, platformColours::textDim);
    addAndMakeVisible (titleLabel);

    styleCaption (urlLabel, "URL");
    addAndMakeVisible (urlLabel);
    styleEditor (urlEditor, Platform::defaultUrl);
    addAndMakeVisible (urlEditor);

    styleCaption (apiKeyLabel, "API key");
    addAndMakeVisible (apiKeyLabel);
    styleEditor (apiKeyEditor, "Optional for a local platform");
    // Same posture as the ACE-Step key field: masked on screen, and the README is
    // explicit that the settings file holds it in plaintext.
    apiKeyEditor.setPasswordCharacter ((juce::juce_wchar) 0x2022);
    addAndMakeVisible (apiKeyEditor);

    connectButton.onClick = [this] { connect(); };
    addAndMakeVisible (connectButton);

    styleCaption (workspaceLabel, "Workspace");
    addAndMakeVisible (workspaceLabel);
    workspaceSelector.setColour (juce::ComboBox::backgroundColourId, platformColours::field);
    workspaceSelector.setColour (juce::ComboBox::textColourId, platformColours::text);
    workspaceSelector.setColour (juce::ComboBox::outlineColourId, platformColours::edge);
    workspaceSelector.onChange = [this] { refreshClips(); };
    addAndMakeVisible (workspaceSelector);

    styleEditor (searchEditor, "Search title or style");
    searchEditor.onReturnKey = [this] { refreshClips(); };
    addAndMakeVisible (searchEditor);

    clipList.setColour (juce::ListBox::backgroundColourId, platformColours::field);
    clipList.setRowHeight (22);
    addAndMakeVisible (clipList);

    importButton.onClick = [this] { importSelectedClip(); };
    addAndMakeVisible (importButton);

    pushButton.onClick = [this]
    {
        // The most recent generated clip is the one a musician means by "push this".
        if (const auto& produced = generation.getClips(); ! produced.isEmpty())
            pushClip (produced.getLast());
        else
            applyStatus ("Generate something first — there is nothing to push", true);
    };
    addAndMakeVisible (pushButton);

    statusLabel.setFont (juce::FontOptions (12.0f));
    statusLabel.setColour (juce::Label::textColourId, platformColours::textDim);
    addAndMakeVisible (statusLabel);

    if (settings != nullptr)
    {
        urlEditor.setText (settings->getValue (Platform::urlKey, Platform::defaultUrl), false);
        apiKeyEditor.setText (settings->getValue (Platform::apiKeyKey), false);
    }

    refresh();
    startTimerHz (2);
}

PlatformPanel::~PlatformPanel()
{
    stopTimer();
}

//==============================================================================
void PlatformPanel::paint (juce::Graphics& g)
{
    auto bounds = getLocalBounds().toFloat();

    g.setColour (platformColours::fill);
    g.fillRoundedRectangle (bounds, 6.0f);

    g.setColour (platformColours::edge);
    g.drawRoundedRectangle (bounds.reduced (0.5f), 6.0f, 1.0f);
}

void PlatformPanel::resized()
{
    auto area = getLocalBounds().reduced (12, 8);

    titleLabel.setBounds (area.removeFromTop (18));
    area.removeFromTop (4);

    auto credentialsRow = area.removeFromTop (24);
    urlLabel.setBounds (credentialsRow.removeFromLeft (34));
    urlEditor.setBounds (credentialsRow.removeFromLeft (juce::jmax (120, credentialsRow.getWidth() / 3)));
    credentialsRow.removeFromLeft (8);
    apiKeyLabel.setBounds (credentialsRow.removeFromLeft (54));
    apiKeyEditor.setBounds (credentialsRow.removeFromLeft (juce::jmax (100, credentialsRow.getWidth() - 96)));
    credentialsRow.removeFromLeft (8);
    connectButton.setBounds (credentialsRow.removeFromLeft (juce::jmin (88, credentialsRow.getWidth())));

    area.removeFromTop (6);

    auto browseRow = area.removeFromTop (24);
    workspaceLabel.setBounds (browseRow.removeFromLeft (68));
    workspaceSelector.setBounds (browseRow.removeFromLeft (juce::jmax (110, browseRow.getWidth() / 3)));
    browseRow.removeFromLeft (8);
    searchEditor.setBounds (browseRow);

    area.removeFromTop (6);

    auto actions = area.removeFromBottom (24);
    importButton.setBounds (actions.removeFromLeft (90));
    actions.removeFromLeft (8);
    pushButton.setBounds (actions.removeFromLeft (180));
    actions.removeFromLeft (8);
    statusLabel.setBounds (actions);

    area.removeFromBottom (6);
    clipList.setBounds (area);
}

//==============================================================================
bool PlatformPanel::hasCredentials() const
{
    return urlEditor.getText().trim().isNotEmpty();
}

juce::String PlatformPanel::getUrl() const       { return urlEditor.getText().trim(); }
juce::String PlatformPanel::getApiKey() const    { return apiKeyEditor.getText(); }

juce::String PlatformPanel::getSelectedWorkspaceId() const
{
    const auto index = workspaceSelector.getSelectedId() - 1;
    return juce::isPositiveAndBelow (index, workspaces.size()) ? workspaces[index].id : juce::String();
}

void PlatformPanel::applyStatus (const juce::String& message, bool isError)
{
    statusLabel.setColour (juce::Label::textColourId,
                           isError ? platformColours::bad : platformColours::textDim);

    if (statusLabel.getText() != message)
        statusLabel.setText (message, juce::dontSendNotification);
}

void PlatformPanel::timerCallback()
{
    refresh();
}

void PlatformPanel::refresh()
{
    const auto canTry = hasCredentials() && ! busy;

    connectButton.setEnabled (canTry);
    workspaceSelector.setEnabled (connected && ! busy);
    searchEditor.setEnabled (connected && ! busy);
    clipList.setEnabled (connected && ! busy);
    importButton.setEnabled (connected && ! busy && clipList.getSelectedRow() >= 0);
    pushButton.setEnabled (connected && ! busy && getSelectedWorkspaceId().isNotEmpty());

    if (busy)
        return;

    if (! hasCredentials())
    {
        // The plugin is fully usable without any of this, and says so rather than
        // looking broken.
        applyStatus ("Not connected — the plugin works fine without the platform", false);
    }
    else if (! Platform::hasTlsSupport() && getUrl().startsWithIgnoreCase ("https:"))
    {
        applyStatus ("This build has no HTTPS support (built without libcurl)", true);
    }
}

//==============================================================================
void PlatformPanel::connect()
{
    if (busy || ! hasCredentials())
        return;

    if (const auto problem = Platform::findUrlProblem (getUrl()); problem.isNotEmpty())
    {
        applyStatus (problem, true);
        return;
    }

    if (settings != nullptr)
    {
        settings->setValue (Platform::urlKey, getUrl());
        settings->setValue (Platform::apiKeyKey, getApiKey());
        settings->saveIfNeeded();
    }

    busy = true;
    applyStatus ("Connecting…", false);
    refresh();

    const auto url = getUrl();
    const auto key = getApiKey();
    const auto request = ++currentRequest;
    juce::WeakReference<PlatformPanel> safeThis { this };

    queue.enqueue ([safeThis, url, key, request]
    {
        auto result = Platform::listWorkspaces (url, key);

        BackgroundTaskQueue::callOnMessageThread ([safeThis, result, request]
        {
            if (auto* panel = safeThis.get(); panel != nullptr && panel->currentRequest == request)
                panel->applyWorkspaces (result);
        });
    });
}

void PlatformPanel::applyWorkspaces (const Platform::Result& result)
{
    busy = false;

    if (result.cancelled)
        return;

    if (! result.ok)
    {
        connected = false;
        workspaceSelector.clear (juce::dontSendNotification);
        applyStatus (result.errorMessage, true);
        refresh();
        return;
    }

    workspaces = result.workspaces;
    workspaceSelector.clear (juce::dontSendNotification);

    for (int i = 0; i < workspaces.size(); ++i)
        workspaceSelector.addItem (workspaces[i].name.isNotEmpty() ? workspaces[i].name
                                                                   : workspaces[i].id,
                                   i + 1);

    connected = true;

    if (workspaces.isEmpty())
    {
        applyStatus ("Connected — no workspaces on the platform yet", false);
        refresh();
        return;
    }

    // Restore the workspace last used, when it is still there.
    int selected = 1;

    if (settings != nullptr)
    {
        const auto saved = settings->getValue (Platform::workspaceKey);

        for (int i = 0; i < workspaces.size(); ++i)
            if (workspaces[i].id == saved)
                selected = i + 1;
    }

    workspaceSelector.setSelectedId (selected, juce::dontSendNotification);
    applyStatus ("Connected — " + juce::String (workspaces.size()) + " workspaces", false);
    refreshClips();
}

void PlatformPanel::refreshClips()
{
    if (busy || ! connected)
        return;

    const auto workspaceId = getSelectedWorkspaceId();

    if (settings != nullptr && workspaceId.isNotEmpty())
    {
        settings->setValue (Platform::workspaceKey, workspaceId);
        settings->saveIfNeeded();
    }

    busy = true;
    refresh();

    const auto url = getUrl();
    const auto key = getApiKey();
    const auto search = searchEditor.getText();
    const auto request = ++currentRequest;
    juce::WeakReference<PlatformPanel> safeThis { this };

    queue.enqueue ([safeThis, url, key, workspaceId, search, request]
    {
        auto result = Platform::listClips (url, key, workspaceId, search);

        BackgroundTaskQueue::callOnMessageThread ([safeThis, result, request]
        {
            if (auto* panel = safeThis.get(); panel != nullptr && panel->currentRequest == request)
                panel->applyClips (result);
        });
    });
}

void PlatformPanel::applyClips (const Platform::Result& result)
{
    busy = false;

    if (result.cancelled)
        return;

    if (! result.ok)
    {
        applyStatus (result.errorMessage, true);
        refresh();
        return;
    }

    clips = result.clips;
    clipList.deselectAllRows();
    clipList.updateContent();

    applyStatus (clips.isEmpty() ? juce::String ("No clips match")
                                 : juce::String (clips.size()) + " clips", false);
    refresh();
}

//==============================================================================
void PlatformPanel::importSelectedClip()
{
    const auto row = clipList.getSelectedRow();

    if (busy || ! juce::isPositiveAndBelow (row, clips.size()))
        return;

    const auto clip = clips[row];
    const auto extension = clip.format.isNotEmpty() ? clip.format : juce::String ("wav");

    // Into the same cache the generated clips live in, so an imported clip is
    // draggable and browsable exactly like a local one.
    const auto destination = generation.getClipDirectory()
                                 .getChildFile ("platform")
                                 .getChildFile (clip.id + "." + extension);

    busy = true;
    applyStatus ("Importing…", false);
    refresh();

    const auto url = getUrl();
    const auto key = getApiKey();
    const auto request = ++currentRequest;
    juce::WeakReference<PlatformPanel> safeThis { this };

    queue.enqueue ([safeThis, url, key, clip, destination, request]
    {
        auto result = Platform::downloadClip (url, key, clip.id, destination);

        BackgroundTaskQueue::callOnMessageThread ([safeThis, result, request, clip]
        {
            auto* panel = safeThis.get();

            if (panel == nullptr || panel->currentRequest != request)
                return;

            panel->busy = false;

            if (result.cancelled)
                return;

            if (! result.ok)
            {
                panel->applyStatus (result.errorMessage, true);
                panel->refresh();
                return;
            }

            // Published through the generation manager, which is what the results
            // panel shows and what makes the clip draggable onto the timeline.
            panel->generation.setClipsForTesting ({ result.file }, clip.bpm);
            panel->applyStatus ("Imported " + result.file.getFileName()
                                    + " — drag it from Results onto a track", false);
            panel->refresh();
        });
    });
}

void PlatformPanel::pushClip (const juce::File& clip)
{
    if (busy)
        return;

    const auto workspaceId = getSelectedWorkspaceId();

    if (workspaceId.isEmpty())
    {
        applyStatus ("Choose a workspace to push to", true);
        return;
    }

    if (! clip.existsAsFile())
    {
        applyStatus ("That clip is no longer on disk", true);
        return;
    }

    busy = true;
    applyStatus ("Pushing " + clip.getFileName() + "…", false);
    refresh();

    const auto url = getUrl();
    const auto key = getApiKey();
    const auto title = clip.getFileNameWithoutExtension();
    const auto bpm = generation.getRequestedBpm();
    const auto request = ++currentRequest;
    juce::WeakReference<PlatformPanel> safeThis { this };

    queue.enqueue ([safeThis, url, key, workspaceId, clip, title, bpm, request]
    {
        auto result = Platform::uploadClip (url, key, workspaceId, clip, title, bpm, {}, 0.0);

        BackgroundTaskQueue::callOnMessageThread ([safeThis, result, request]
        {
            auto* panel = safeThis.get();

            if (panel == nullptr || panel->currentRequest != request)
                return;

            panel->busy = false;

            if (result.cancelled)
                return;

            panel->applyStatus (result.ok ? "Pushed to the platform" : result.errorMessage, ! result.ok);
            panel->refresh();

            if (result.ok)
                panel->refreshClips();
        });
    });
}

} // namespace acemusic
