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
    switch (status)
    {
        case Status::Disconnected:  return "Not connected";
        case Status::Connecting:    return "Connecting…";
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

    queue.enqueue ([weakSelf, queuePtr, urlToProbe, keyToUse]
    {
        const auto result = probeAceStepServer (urlToProbe,
                                                keyToUse,
                                                [queuePtr] { return queuePtr->isStopping(); },
                                                defaultProbeTimeoutMs);

        BackgroundTaskQueue::callOnMessageThread ([weakSelf, result]
        {
            // Gone while the probe was in flight — nothing to update.
            if (auto* self = weakSelf.get())
                self->applyResult (result);
        });
    });
}

void ConnectionManager::autoConnect()
{
    if (settings.serverUrl.trim().isNotEmpty())
        testConnection();
}

void ConnectionManager::applyResult (const ProbeResult& result)
{
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

        statusMessage = "Connected — " + juce::String (models.size())
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
