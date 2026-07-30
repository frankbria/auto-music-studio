#include "ConnectionManager.h"

namespace acemusic
{

ConnectionManager::ConnectionManager (BackgroundTaskQueue& queueToUse, juce::PropertiesFile* propertiesToUse)
    : queue (queueToUse),
      properties (propertiesToUse)
{
    if (properties != nullptr)
        settings = ConnectionSettings::readFrom (*properties);
}

ConnectionManager::~ConnectionManager()
{
    // Nothing to cancel: a probe in flight holds only a WeakReference to us, so it
    // becomes a no-op the moment this destructor runs. The queue's own teardown is
    // what waits for the worker.
    masterReference.clear();
}

juce::String ConnectionManager::describe (Status status)
{
    // ASCII only. A non-ASCII literal here renders as mojibake in the plugin UI —
    // JUCE draws it through the platform font stack, and the source charset is not
    // guaranteed across MSVC/clang/GCC. See isAsciiOnly() in the tests.
    switch (status)
    {
        case Status::Disconnected:  return "Not connected";
        case Status::Connecting:    return "Connecting...";
        case Status::Connected:     return "Connected";
        case Status::Error:         return "Error";
    }

    return "Unknown";
}

void ConnectionManager::setSettings (const ConnectionSettings& newSettings)
{
    // Only the server identity invalidates a connection; picking a different model
    // does not.
    const auto serverChanged = newSettings.serverUrl.trim() != settings.serverUrl.trim()
                            || newSettings.apiKey != settings.apiKey;

    settings = newSettings;
    settings.serverUrl = settings.serverUrl.trim();

    if (properties != nullptr)
        settings.writeTo (*properties);

    if (serverChanged)
    {
        // Invalidate any probe already in flight: its result describes the server we
        // just navigated away from.
        ++serverGeneration;

        // A green light for the server we are no longer pointing at would be a lie,
        // and the old model list belongs to that server too.
        status = Status::Disconnected;
        statusMessage = describe (Status::Disconnected);
        models.clear();
    }

    sendChangeMessage();
}

void ConnectionManager::setSelectedModel (const juce::String& modelId)
{
    if (settings.modelId == modelId)
        return;

    settings.modelId = modelId;

    if (properties != nullptr)
        settings.writeTo (*properties);

    sendChangeMessage();
}

void ConnectionManager::testConnection()
{
    if (isBusy())
        return;

    status = Status::Connecting;
    statusMessage = describe (Status::Connecting);
    sendChangeMessage();

    // Snapshot the settings so the worker never reads state the message thread can
    // change underneath it — that's what keeps this class lock-free.
    const auto urlToProbe = settings.serverUrl;
    const auto keyToUse   = settings.apiKey;

    juce::WeakReference<ConnectionManager> weakSelf (this);
    auto* queuePtr = &queue;
    const auto generation = serverGeneration;

    queue.enqueue ([weakSelf, queuePtr, urlToProbe, keyToUse, generation]
    {
        const auto result = probeAceStepServer (urlToProbe,
                                                keyToUse,
                                                [queuePtr] { return queuePtr->isStopping(); },
                                                defaultProbeTimeoutMs);

        BackgroundTaskQueue::callOnMessageThread ([weakSelf, result, generation]
        {
            // Gone while the probe was in flight — nothing to update.
            if (auto* self = weakSelf.get())
                self->applyResult (result, generation);
        });
    });
}

void ConnectionManager::autoConnect()
{
    if (settings.serverUrl.trim().isNotEmpty())
        testConnection();
}

void ConnectionManager::applyResult (const ProbeResult& result, int fromGeneration)
{
    if (fromGeneration != serverGeneration)
    {
        // The user pointed us somewhere else while this was in flight. Applying it
        // would show the previous server's models under the new URL.
        return;
    }

    if (result.cancelled)
    {
        // Teardown asked the probe to stop; leaving an error on screen would be
        // misleading about the server.
        status = Status::Disconnected;
        statusMessage = describe (Status::Disconnected);
        sendChangeMessage();
        return;
    }

    if (result.ok)
    {
        status = Status::Connected;
        models = result.models;

        statusMessage = "Connected - " + juce::String (models.size())
                      + (models.size() == 1 ? " model available" : " models available");

        // Drop a selection the new server doesn't offer, and pick a default when
        // there isn't a valid one, so the dropdown is never showing a stale model.
        if (! models.contains (settings.modelId))
        {
            settings.modelId = models[0];

            if (properties != nullptr)
                settings.writeTo (*properties);
        }
    }
    else
    {
        status = Status::Error;
        models.clear();
        statusMessage = result.errorMessage.isNotEmpty() ? result.errorMessage
                                                         : juce::String ("Connection failed");
    }

    sendChangeMessage();
}

} // namespace acemusic
