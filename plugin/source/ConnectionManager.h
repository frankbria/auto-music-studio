#pragma once

#include "AceStepClient.h"
#include "BackgroundTaskQueue.h"
#include "ConnectionSettings.h"

namespace acemusic
{

/**
    Owns the plugin's view of the ACE-Step server: the settings, the current status,
    and the model list.

    Lives on the **processor**, not the editor — the editor is destroyed whenever the
    user closes the plugin window, and both the auto-connect on load and its result
    have to outlive that. ConnectionPanel is a ChangeListener on this.

    All state here is read and written on the message thread only; probes run on the
    BackgroundTaskQueue against a *copy* of the settings, so there is no lock. The
    result comes back via BackgroundTaskQueue::callOnMessageThread, guarded by a
    WeakReference so a probe finishing after teardown is a no-op.
*/
class ConnectionManager final : public juce::ChangeBroadcaster
{
public:
    enum class Status
    {
        Disconnected,   ///< never tried, or settings changed since the last try
        Connecting,     ///< a probe is in flight
        Connected,      ///< server answered and reported at least one model
        Error           ///< unreachable, rejected, or unusable response
    };

    /** @param queue       where probes run; must outlive this object
        @param properties  settings store; null means "don't persist" (tests) */
    ConnectionManager (BackgroundTaskQueue& queue, juce::PropertiesFile* properties);
    ~ConnectionManager() override;

    //==============================================================================
    ConnectionSettings getSettings() const                    { return settings; }

    /** Applies and persists new settings. If the server identity changed, the status
        resets to Disconnected — a green light for the *previous* server would be a
        lie. Broadcasts either way. */
    void setSettings (const ConnectionSettings& newSettings);

    /** Records the chosen model without disturbing the connection status. */
    void setSelectedModel (const juce::String& modelId);

    //==============================================================================
    Status getStatus() const noexcept                         { return status; }
    juce::String getStatusMessage() const                     { return statusMessage; }
    const juce::StringArray& getModels() const noexcept       { return models; }

    /** Human-readable label for the indicator. */
    static juce::String describe (Status);

    //==============================================================================
    /** Starts a probe. Returns immediately; the status goes to Connecting and the
        result arrives as a change broadcast. A second call while one is in flight is
        ignored. */
    void testConnection();

    /** Probe once on plugin load. Separate from testConnection() so constructing a
        manager never fires network traffic on its own — the processor decides when
        load has happened, and tests that aren't about auto-connect stay fast. */
    void autoConnect();

    /** True while a probe is in flight. */
    bool isBusy() const noexcept                              { return status == Status::Connecting; }

private:
    void applyResult (const ProbeResult&, int fromGeneration);

    /** Bumped whenever the server identity changes. A probe carries the value it
        started with, so a result from a server the user has since navigated away
        from can be discarded instead of lighting the indicator green with the old
        server's models. */
    int serverGeneration = 0;

    BackgroundTaskQueue& queue;
    juce::PropertiesFile* properties = nullptr;

    ConnectionSettings settings;
    Status status = Status::Disconnected;
    juce::String statusMessage { "Not connected" };
    juce::StringArray models;

    JUCE_DECLARE_WEAK_REFERENCEABLE (ConnectionManager)
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ConnectionManager)
};

} // namespace acemusic
