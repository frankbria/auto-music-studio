#pragma once

#include <juce_core/juce_core.h>

#include <atomic>
#include <functional>

namespace acemusic
{

/**
    Runs work off the audio thread.

    Every call the plugin makes to the ACE-Step server goes through here, so the
    audio callback never blocks on a socket. `processBlock` must not touch this
    class at all — it allocates and takes locks. Enqueue from the message thread
    (UI callbacks, timers) and marshal results back with callOnMessageThread().

    ## Shutdown

    The destructor sets isStopping() and then lets ~juce::ThreadPool() interrupt and
    wait for in-flight work: removeAllJobs (true, 5000) followed by stopThreads(),
    which allows each worker a further 500ms. A task that ignores the stop request
    is abandoned still running after that — measured at 5502ms for one worker, with
    the task unfinished — which in a DAW means teardown blocks for five and a half
    seconds and leaves a thread behind.

    So any task that can run longer than a few hundred milliseconds — every HTTP
    request — MUST cooperate: poll isStopping() around its slow steps and cancel its
    I/O (juce::WebInputStream::cancel) when it goes true. A cooperating task lets
    teardown return in single-digit milliseconds, which the test suite covers; the
    5502ms figure above came from a throwaway probe, not a committed test, because
    the abandoned thread it leaves behind has no business running in CI.

    The queue outlives all of its jobs, so calling isStopping() from inside a task
    is always safe.
*/
class BackgroundTaskQueue
{
public:
    /** @param numThreads  concurrent workers; one is enough for serialised
                           request/response traffic against a local server. */
    explicit BackgroundTaskQueue (int numThreads = 1);

    /** Signals in-flight work to stop, then waits for it. See "Shutdown" above. */
    ~BackgroundTaskQueue();

    /** Queues `task` to run on a worker thread. Safe to call from any
        non-audio thread. */
    void enqueue (std::function<void()> task);

    /** Delivers `callback` on the message thread. Use this to hand a background
        result to the UI — JUCE components may only be touched there.

        The callback must not capture a raw pointer to anything that can be
        destroyed before it fires; use juce::Component::SafePointer or a
        juce::WeakReference. */
    static void callOnMessageThread (std::function<void()> callback);

    /** True once the queue has started shutting down.

        Long-running tasks must poll this and return early — that is the only
        thing keeping plugin teardown from blocking on a slow request. */
    bool isStopping() const noexcept                          { return stopping.load(); }

    /** Blocks until the queue is empty or the timeout elapses.
        @returns true if the queue drained. For tests and shutdown only. */
    bool waitForAll (int timeoutMs);

    /** Jobs queued or running right now. */
    int getNumPending() const;

private:
    // Declared before `pool` so it is destroyed *after* it: members tear down in
    // reverse order, so a job still winding up inside ~ThreadPool() can safely
    // read this flag.
    std::atomic<bool> stopping { false };

    juce::ThreadPool pool;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (BackgroundTaskQueue)
};

} // namespace acemusic
