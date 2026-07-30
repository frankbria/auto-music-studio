#pragma once

#include <juce_core/juce_core.h>

#include <functional>

namespace acemusic
{

/**
    Runs work off the audio thread.

    Every call the plugin makes to the ACE-Step server goes through here, so the
    audio callback never blocks on a socket. `processBlock` must not touch this
    class at all — it allocates and takes locks. Enqueue from the message thread
    (UI callbacks, timers) and marshal results back with callOnMessageThread().

    On destruction, running work is interrupted and waited on for at most
    shutdownTimeoutMs. A task that can block for longer than that — an HTTP
    request, say — is responsible for being cancellable by its owner
    (juce::WebInputStream::cancel), otherwise closing the plugin in a DAW will
    stall for the full duration of the request.
*/
class BackgroundTaskQueue
{
public:
    /** @param numThreads  concurrent workers; one is enough for serialised
                           request/response traffic against a local server. */
    explicit BackgroundTaskQueue (int numThreads = 1);

    /** Waits up to shutdownTimeoutMs for running work, then abandons the rest. */
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

    /** Blocks until the queue is empty or the timeout elapses.
        @returns true if the queue drained. For tests and shutdown only. */
    bool waitForAll (int timeoutMs);

    /** Jobs queued or running right now. */
    int getNumPending() const;

    /** How long the destructor waits for in-flight work before abandoning it. */
    static constexpr int shutdownTimeoutMs = 2000;

private:
    juce::ThreadPool pool;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (BackgroundTaskQueue)
};

} // namespace acemusic
