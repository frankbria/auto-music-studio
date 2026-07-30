#include "BackgroundTaskQueue.h"

#include <juce_events/juce_events.h>

#include <atomic>
#include <thread>

namespace acemusic
{

class BackgroundTaskQueueTests final : public juce::UnitTest
{
public:
    BackgroundTaskQueueTests()
        : juce::UnitTest ("BackgroundTaskQueue", "acemusic")
    {
    }

    void runTest() override
    {
        beginTest ("runs queued work off the calling thread");
        {
            BackgroundTaskQueue queue;
            const auto callingThread = std::this_thread::get_id();

            std::atomic<bool> ran { false };
            std::thread::id ranOn {};

            queue.enqueue ([&]
            {
                ranOn = std::this_thread::get_id();
                ran = true;
            });

            expect (queue.waitForAll (5000), "queue did not drain");
            expect (ran.load(), "task never ran");
            expect (ranOn != callingThread, "task ran on the calling thread");
        }

        beginTest ("runs every queued task");
        {
            BackgroundTaskQueue queue { 2 };
            std::atomic<int> count { 0 };

            for (int i = 0; i < 50; ++i)
                queue.enqueue ([&] { ++count; });

            expect (queue.waitForAll (5000), "queue did not drain");
            expectEquals (count.load(), 50);
        }

        beginTest ("ignores an empty task");
        {
            BackgroundTaskQueue queue;
            queue.enqueue (nullptr);
            expectEquals (queue.getNumPending(), 0);
        }

        beginTest ("reports pending work");
        {
            BackgroundTaskQueue queue;
            juce::WaitableEvent release;

            queue.enqueue ([&] { release.wait (5000); });
            expect (queue.getNumPending() > 0, "queued job was not counted");

            release.signal();
            expect (queue.waitForAll (5000), "queue did not drain");
            expectEquals (queue.getNumPending(), 0);
        }

        beginTest ("waitForAll reports failure on timeout");
        {
            BackgroundTaskQueue queue;
            juce::WaitableEvent release;

            queue.enqueue ([&] { release.wait (5000); });
            expect (! queue.waitForAll (50), "waitForAll claimed a blocked queue had drained");

            release.signal();
            expect (queue.waitForAll (5000), "queue did not drain after release");
        }

        beginTest ("callOnMessageThread delivers on the message thread");
        {
            BackgroundTaskQueue queue;
            std::atomic<bool> delivered { false };
            std::atomic<bool> onMessageThread { false };
            std::atomic<bool> workerWasMessageThread { true };

            auto* mm = juce::MessageManager::getInstance();

            queue.enqueue ([&]
            {
                // A background worker is, by definition, not the message thread.
                workerWasMessageThread = mm->isThisTheMessageThread();

                BackgroundTaskQueue::callOnMessageThread ([&]
                {
                    onMessageThread = mm->isThisTheMessageThread();
                    delivered = true;
                });
            });

            expect (queue.waitForAll (5000), "queue did not drain");

            // Pump the message loop until the async callback lands.
            const auto deadline = juce::Time::getMillisecondCounter() + 5000;
            while (! delivered.load() && juce::Time::getMillisecondCounter() < deadline)
                mm->runDispatchLoopUntil (10);

            expect (delivered.load(), "callback was never delivered");
            expect (! workerWasMessageThread.load(), "the worker ran on the message thread");
            expect (onMessageThread.load(), "callback did not run on the message thread");
        }
    }
};

static BackgroundTaskQueueTests backgroundTaskQueueTests;

} // namespace acemusic
