#include "BackgroundTaskQueue.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

BackgroundTaskQueue::BackgroundTaskQueue (int numThreads)
    : pool (juce::ThreadPool::Options{}
                .withThreadName ("AceMusic background")
                .withNumberOfThreads (juce::jmax (1, numThreads)))
{
}

BackgroundTaskQueue::~BackgroundTaskQueue()
{
    // Interrupt rather than wait indefinitely: a request against a hung server
    // must never stall the DAW closing the plugin.
    pool.removeAllJobs (true, shutdownTimeoutMs);
}

void BackgroundTaskQueue::enqueue (std::function<void()> task)
{
    if (task == nullptr)
        return;

    pool.addJob (std::move (task));
}

void BackgroundTaskQueue::callOnMessageThread (std::function<void()> callback)
{
    if (callback == nullptr)
        return;

    juce::MessageManager::callAsync (std::move (callback));
}

bool BackgroundTaskQueue::waitForAll (int timeoutMs)
{
    // ponytail: poll rather than add a condition variable — the only callers are
    // tests and shutdown, neither of which is latency-sensitive.
    const auto deadline = juce::Time::getMillisecondCounter() + (juce::uint32) juce::jmax (0, timeoutMs);

    while (pool.getNumJobs() > 0)
    {
        if (juce::Time::getMillisecondCounter() >= deadline)
            return false;

        juce::Thread::sleep (5);
    }

    return true;
}

int BackgroundTaskQueue::getNumPending() const
{
    return pool.getNumJobs();
}

} // namespace acemusic
