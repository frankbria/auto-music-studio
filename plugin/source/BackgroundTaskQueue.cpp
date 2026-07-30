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
    // Tell cooperating tasks to bail out. ~ThreadPool() then does the interrupting
    // and waiting itself (removeAllJobs (true, 5000) followed by stopThreads()),
    // so calling removeAllJobs here as well would only add another timeout to the
    // worst case without changing the outcome.
    stopping = true;
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
    const auto start = juce::Time::getMillisecondCounter();
    const auto limit = (juce::uint32) juce::jmax (0, timeoutMs);

    while (pool.getNumJobs() > 0)
    {
        // Unsigned subtraction, so this stays correct across the counter's
        // ~49-day wrap.
        if ((juce::uint32) (juce::Time::getMillisecondCounter() - start) >= limit)
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
