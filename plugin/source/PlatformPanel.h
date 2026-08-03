#pragma once

#include "BackgroundTaskQueue.h"
#include "GenerationManager.h"
#include "PlatformClient.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace acemusic
{

/**
    Browse the musician's platform workspaces and clips, import one into the DAW, and
    push a local clip back up (US-24.5).

    **Entirely optional.** With no credentials set, this panel says so and everything
    else in the plugin works exactly as it did — the plugin is usable offline against a
    local ACE-Step server and never needs the platform. Nothing here shares state with
    the generation path, which is what keeps a platform outage from touching it.

    Every request goes through the shared BackgroundTaskQueue, so neither the audio nor
    the message thread ever waits on the network.
*/
class PlatformPanel final : public juce::Component,
                            private juce::Timer
{
public:
    /** @param settings  where the platform URL, key and last workspace persist; null
                         means "do not persist", which is what tests get */
    PlatformPanel (BackgroundTaskQueue&, GenerationManager&, juce::PropertiesFile* settings = nullptr);
    ~PlatformPanel() override;

    void paint (juce::Graphics&) override;
    void resized() override;

    //==============================================================================
    /** Saves what is typed and re-reads the workspace list. */
    void connect();

    /** Re-reads the clip list for the selected workspace and search text. */
    void refreshClips();

    /** Downloads the selected clip into the cache and shows it in Results. */
    void importSelectedClip();

    /** Pushes `clip` to the selected workspace. */
    void pushClip (const juce::File& clip);

    //==============================================================================
    // Test seams.
    juce::TextEditor& getUrlEditor() noexcept                 { return urlEditor; }
    juce::TextEditor& getApiKeyEditor() noexcept              { return apiKeyEditor; }
    juce::TextEditor& getSearchEditor() noexcept              { return searchEditor; }
    juce::ComboBox&   getWorkspaceSelector() noexcept         { return workspaceSelector; }
    juce::ListBox&    getClipList() noexcept                  { return clipList; }
    juce::TextButton& getConnectButton() noexcept             { return connectButton; }
    juce::TextButton& getImportButton() noexcept              { return importButton; }
    juce::TextButton& getPushButton() noexcept                { return pushButton; }
    juce::Label&      getStatusLabel() noexcept               { return statusLabel; }

    /** Clips currently listed. */
    const juce::Array<Platform::Clip>& getClips() const noexcept { return clips; }

    /** True once a workspace list has come back. */
    bool isConnected() const noexcept                         { return connected; }

    /** True when there is enough configuration to try at all. */
    bool hasCredentials() const;

private:
    void timerCallback() override;
    void refresh();

    /** Applies a finished call on the message thread. */
    void applyWorkspaces (const Platform::Result&);
    void applyClips (const Platform::Result&);
    void applyStatus (const juce::String& message, bool isError);

    juce::String getUrl() const;
    juce::String getApiKey() const;
    juce::String getSelectedWorkspaceId() const;

    /** Rows of clips: title, then bpm/key/duration. */
    class ClipListModel final : public juce::ListBoxModel
    {
    public:
        explicit ClipListModel (PlatformPanel& ownerToUse) : owner (ownerToUse) {}

        int getNumRows() override;
        void paintListBoxItem (int row, juce::Graphics&, int width, int height, bool selected) override;
        void selectedRowsChanged (int lastRowSelected) override;

    private:
        PlatformPanel& owner;
    };

    BackgroundTaskQueue& queue;
    GenerationManager& generation;
    juce::PropertiesFile* settings = nullptr;

    juce::Label      titleLabel;
    juce::Label      urlLabel;
    juce::TextEditor urlEditor;
    juce::Label      apiKeyLabel;
    juce::TextEditor apiKeyEditor;
    juce::TextButton connectButton { "Connect" };

    juce::Label      workspaceLabel;
    juce::ComboBox   workspaceSelector;
    juce::TextEditor searchEditor;

    ClipListModel    clipModel { *this };
    juce::ListBox    clipList { "platform clips", &clipModel };

    juce::TextButton importButton { "Import" };
    juce::TextButton pushButton { "Push selected local clip" };
    juce::Label      statusLabel;

    juce::Array<Platform::Workspace> workspaces;
    juce::Array<Platform::Clip> clips;

    bool connected = false;
    bool busy = false;

    /** Discards results from a call the user has already superseded. */
    int currentRequest = 0;

    JUCE_DECLARE_WEAK_REFERENCEABLE (PlatformPanel)
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PlatformPanel)
};

} // namespace acemusic
