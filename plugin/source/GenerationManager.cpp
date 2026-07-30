#include "GenerationManager.h"

namespace acemusic
{

GenerationManager::GenerationManager (BackgroundTaskQueue& queueToUse,
                                      ConnectionManager& connectionToUse,
                                      juce::PropertiesFile* settings)
    : queue (queueToUse),
      connection (connectionToUse),
      cache (settings)
{
}

GenerationManager::~GenerationManager()
{
    // Tell a run in flight to stop at its next poll. It holds a share of the control
    // block, so this is safe even though the manager is going away underneath it.
    if (activeControl != nullptr)
        activeControl->stopped = true;

    masterReference.clear();
}

juce::String GenerationManager::describe (State state) noexcept
{
    switch (state)
    {
        case State::idle:         return "Idle";
        case State::submitting:   return "Submitting...";
        case State::queued:       return "Queued on the server...";
        case State::running:      return "Generating...";
        case State::downloading:  return "Downloading clips...";
        case State::complete:     return "Complete";
        case State::failed:       return "Failed";
        case State::cancelled:    return "Cancelled";
    }

    return "Unknown";
}

juce::File GenerationManager::getClipDirectory() const
{
    return cache.getDirectory();
}

bool GenerationManager::isBusy() const noexcept
{
    return state == State::submitting
        || state == State::queued
        || state == State::running
        || state == State::downloading;
}

int GenerationManager::getElapsedSeconds() const
{
    if (startedAtMs == 0)
        return 0;

    return (int) ((juce::Time::getMillisecondCounter() - startedAtMs) / 1000);
}

juce::String GenerationManager::findStartProblem (const GenerationRequest& request) const
{
    if (isBusy())
        return "A generation is already running";

    // AC: generation is unavailable unless the server is actually reachable. Starting
    // anyway would just fail slowly with a worse message.
    if (connection.getStatus() != ConnectionManager::Status::Connected)
        return "Connect to an ACE-Step server first";

    return request.findProblem();
}

void GenerationManager::start (const GenerationRequest& request)
{
    if (! canStart (request))
        return;

    // Retire any previous run's control block so a straggler can't post state for a
    // run the user has moved on from.
    if (activeControl != nullptr)
        activeControl->stopped = true;

    ++currentRun;

    RunContext context;
    context.request        = request;
    context.request.model  = connection.getSettings().modelId;
    context.serverUrl      = connection.getSettings().serverUrl;
    context.apiKey         = connection.getSettings().apiKey;
    context.runId          = currentRun;
    // Resolved here, on the message thread, so the worker never reads settings.
    context.clipDirectory  = getClipDirectory();
    context.control        = std::make_shared<RunControl>();
    context.owner          = this;
    context.queue          = &queue;

    activeControl = context.control;

    clips.clear();
    startedAtMs = juce::Time::getMillisecondCounter();
    state = State::submitting;
    statusMessage = describe (State::submitting);
    sendChangeMessage();

    queue.enqueue ([context] { runGeneration (context); });
}

void GenerationManager::setClipsForTesting (const juce::Array<juce::File>& files)
{
    clips = files;
    state = files.isEmpty() ? State::idle : State::complete;
    statusMessage = files.isEmpty()
                        ? describe (State::idle)
                        : juce::String (files.size())
                              + (files.size() == 1 ? " clip ready" : " clips ready");
    sendChangeMessage();
}

void GenerationManager::cancel()
{
    if (! isBusy())
        return;

    if (activeControl != nullptr)
        activeControl->stopped = true;

    statusMessage = "Cancelling...";
    sendChangeMessage();
}

void GenerationManager::applyState (const RunContext& context, State newState, const juce::String& message)
{
    auto owner = context.owner;
    const auto runId = context.runId;

    BackgroundTaskQueue::callOnMessageThread ([owner, runId, newState, message]
    {
        auto* self = owner.get();

        // The null check is load-bearing and covered: a run outliving its manager is
        // a real, tested case.
        //
        // The run-id check is defence in depth and is NOT currently reachable, so it
        // is deliberately untested rather than covered by a test that only looks like
        // it exercises it. currentRun only advances in start(), start() refuses while
        // isBusy(), and isBusy() stays true until this very callback delivers the
        // worker's terminal state — after which that worker posts nothing more. A
        // stale post therefore cannot coexist with a newer run today. It becomes
        // reachable the moment start() is allowed to pre-empt a running job, which is
        // exactly when losing this would be expensive.
        if (self == nullptr || runId != self->currentRun)
            return;

        self->state = newState;
        self->statusMessage = message.isNotEmpty() ? message : describe (newState);
        self->sendChangeMessage();
    });
}

void GenerationManager::applyClips (const RunContext& context, const juce::Array<juce::File>& downloaded)
{
    auto owner = context.owner;
    const auto runId = context.runId;

    BackgroundTaskQueue::callOnMessageThread ([owner, runId, downloaded]
    {
        auto* self = owner.get();

        // Same reasoning as applyState: null check covered, run-id check defensive.
        if (self == nullptr || runId != self->currentRun)
            return;

        self->clips = downloaded;
        self->sendChangeMessage();
    });
}

void GenerationManager::runGeneration (RunContext context)
{
    // Everything this needs is in `context`. It never dereferences the manager — the
    // only way back is applyState/applyClips, which hop to the message thread and
    // check the WeakReference there.
    const auto shouldStop = [&context]
    {
        return context.control->stopped.load()
            || (context.queue != nullptr && context.queue->isStopping());
    };

    //==============================================================================
    const auto submitted = submitGeneration (context.serverUrl,
                                             context.apiKey,
                                             context.request.toPayloadJson(),
                                             shouldStop);

    if (submitted.cancelled || shouldStop())
    {
        applyState (context, State::cancelled, {});
        return;
    }

    if (! submitted.ok)
    {
        applyState (context, State::failed, submitted.errorMessage);
        return;
    }

    applyState (context, State::queued, {});

    //==============================================================================
    TaskStatus status;
    auto sawRunning = false;

    for (;;)
    {
        // Sliced so a cancel lands within ~100ms rather than a whole interval.
        for (int waited = 0; waited < pollIntervalMs; waited += 100)
        {
            if (shouldStop())
            {
                applyState (context, State::cancelled, {});
                return;
            }

            juce::Thread::sleep (100);
        }

        status = queryTask (context.serverUrl, context.apiKey, submitted.taskId, shouldStop);

        if (status.cancelled || shouldStop())
        {
            applyState (context, State::cancelled, {});
            return;
        }

        if (! status.ok || status.state == TaskStatus::State::failed)
        {
            applyState (context, State::failed, status.errorMessage);
            return;
        }

        if (status.state == TaskStatus::State::completed)
            break;

        // The server reports queued and running with the same integer, so the first
        // successful poll is the most honest moment to start saying "generating".
        if (! sawRunning)
        {
            sawRunning = true;
            applyState (context, State::running, {});
        }
    }

    //==============================================================================
    if (status.audioUrls.isEmpty())
    {
        applyState (context, State::failed, "The server finished but returned no audio");
        return;
    }

    applyState (context, State::downloading, {});

    // A timestamped name keeps runs unique across plugin restarts, where the run
    // counter starts over and would otherwise overwrite an earlier generation. The
    // timestamp is only second-resolution though, so a restart inside the same second
    // could still collide — take the next free suffix rather than overwrite.
    const auto baseName = juce::Time::getCurrentTime().formatted ("%Y%m%d-%H%M%S")
                              + "-run" + juce::String (context.runId);

    auto directory = context.clipDirectory.getChildFile (baseName);

    for (int attempt = 2; directory.exists() && attempt < 100; ++attempt)
        directory = context.clipDirectory.getChildFile (baseName + "-" + juce::String (attempt));

    directory.createDirectory();

    juce::Array<juce::File> downloaded;

    for (int i = 0; i < status.audioUrls.size(); ++i)
    {
        if (shouldStop())
        {
            applyState (context, State::cancelled, {});
            return;
        }

        const auto destination = directory.getChildFile ("clip-" + juce::String (i + 1) + ".wav");
        const auto error = downloadAudio (status.audioUrls[i], context.apiKey, destination, shouldStop);

        if (error.isNotEmpty())
        {
            applyState (context, State::failed, error);
            return;
        }

        if (destination.existsAsFile())
            downloaded.add (destination);
    }

    if (downloaded.isEmpty())
    {
        // Only reachable if every download was cancelled mid-flight.
        applyState (context, State::cancelled, {});
        return;
    }

    // Record what this was, so the cache browser can describe it later. The audio
    // files carry none of it.
    ClipCache::writeMetadata (directory,
                              context.request.prompt,
                              context.request.model,
                              (double) context.request.durationSeconds);

    applyClips (context, downloaded);
    applyState (context, State::complete,
                juce::String (downloaded.size())
                    + (downloaded.size() == 1 ? " clip ready" : " clips ready"));
}

} // namespace acemusic
