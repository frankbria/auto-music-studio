#pragma once

#include "AceStepClient.h"
#include "ClipCache.h"
#include "BackgroundTaskQueue.h"
#include "ConnectionManager.h"
#include "GenerationRequest.h"

#include <atomic>
#include <memory>

namespace acemusic
{

/**
    Drives one generation from submit to downloaded clips.

    ACE-Step generation is submit → poll → download, and the job runs for minutes, so
    the whole sequence is a single background task that polls. It lives on the
    processor for the same reason ConnectionManager does: the editor is destroyed
    whenever the plugin window closes, and a generation has to survive that.

    Same lock-free discipline as ConnectionManager — the worker gets a snapshot, every
    state change is applied on the message thread behind a juce::WeakReference, and a
    run counter discards results from a run the user has already replaced or cancelled.

    Cancellation is at poll granularity: the loop checks between polls rather than
    interrupting a request mid-flight. That is enough because no single request here is
    long — the *job* is long, the requests are not.
*/
class GenerationManager final : public juce::ChangeBroadcaster
{
public:
    enum class State
    {
        idle,
        submitting,     ///< POST /release_task in flight
        queued,         ///< accepted; server reports it as not yet running
        running,        ///< server is generating
        downloading,    ///< fetching the finished clips
        complete,
        failed,
        cancelled
    };

    /** @param settings  used to resolve the configured cache path; null uses the default */
    GenerationManager (BackgroundTaskQueue& queue,
                       ConnectionManager& connection,
                       juce::PropertiesFile* settings = nullptr);
    ~GenerationManager() override;

    /** Starts a generation. Returns immediately; watch for change messages.
        Ignored if one is already in flight, or if the request is invalid — check
        canStart() first for the reason. */
    void start (const GenerationRequest& request);

    /** Asks the current run to stop at its next poll. */
    void cancel();

    /** Why a generation cannot be started right now, or empty if it can. */
    juce::String findStartProblem (const GenerationRequest& request) const;

    bool canStart (const GenerationRequest& request) const  { return findStartProblem (request).isEmpty(); }

    //==============================================================================
    State getState() const noexcept                         { return state; }
    juce::String getStatusMessage() const                   { return statusMessage; }

    /** Downloaded clips, in the order the server listed them. */
    const juce::Array<juce::File>& getClips() const noexcept { return clips; }

    /** The BPM the current clips were asked for, or < 0 when the request left BPM on
        "Auto" and the server chose for itself.

        This is the *requested* tempo, not one measured from the returned audio — which
        is why tempo matching (US-24.1) does nothing for an Auto-BPM generation rather
        than guessing. Detecting the tempo of a finished clip is its own story. */
    int getRequestedBpm() const noexcept                     { return requestedBpm; }

    /** Seconds since the current run started; 0 when idle. */
    int getElapsedSeconds() const;

    bool isBusy() const noexcept;

    static juce::String describe (State) noexcept;

    /** Test seam. Publishes `files` as if a generation had just produced them, so a
        test about the *results* UI does not have to drive a whole submit/poll/download
        cycle first. Message thread only; broadcasts like a real completion.

        Named unmistakably: nothing in the plugin calls this. US-23.5 will need a real
        way to restore clips from the cache, and that should be its own API with its
        own semantics rather than this quietly becoming production behaviour. */
    void setClipsForTesting (const juce::Array<juce::File>& files, int bpm = -1);

    /** Where clips are written: the configured cache path, or ClipCache's default. */
    juce::File getClipDirectory() const;

    /** How long between polls of /query_result. */
    static constexpr int pollIntervalMs = 2000;

private:
    /** The stop flag for one run.

        Held by shared_ptr so the worker owns a share of it: superseding or destroying
        the manager can set it without the worker ever dereferencing the manager. This
        is the whole reason the worker touches no member state directly. */
    struct RunControl
    {
        std::atomic<bool> stopped { false };
    };

    /** Everything one run needs, captured by value on the message thread. */
    struct RunContext
    {
        GenerationRequest request;
        juce::String serverUrl;
        juce::String apiKey;
        int runId = 0;
        juce::File clipDirectory;
        std::shared_ptr<RunControl> control;
        juce::WeakReference<GenerationManager> owner;
        BackgroundTaskQueue* queue = nullptr;
    };

    static void runGeneration (RunContext);
    static void applyState (const RunContext&, State, const juce::String& message);
    static void applyClips (const RunContext&, const juce::Array<juce::File>&);

    BackgroundTaskQueue& queue;
    ConnectionManager& connection;
    ClipCache cache;

    State state = State::idle;
    juce::String statusMessage { "Idle" };
    juce::Array<juce::File> clips;

    /** Kept alongside `clips` so it always describes the clips currently published. */
    int requestedBpm = -1;

    int currentRun = 0;
    juce::uint32 startedAtMs = 0;

    /** Stop flag for the run currently in flight, if any. */
    std::shared_ptr<RunControl> activeControl;

    JUCE_DECLARE_WEAK_REFERENCEABLE (GenerationManager)
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (GenerationManager)
};

} // namespace acemusic
