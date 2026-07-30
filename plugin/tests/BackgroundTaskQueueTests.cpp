#include "BackgroundTaskQueue.h"

#include <juce_events/juce_events.h>

#include <atomic>
#include <memory>
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

        beginTest ("a cooperating task sees isStopping and lets teardown finish promptly");
        {
            // This is the guarantee the header promises, and the only thing keeping
            // a DAW from freezing on teardown while a request is in flight.
            struct Shared
            {
                std::atomic<bool> sawStopRequest { false };
                std::atomic<bool> finished { false };
                std::atomic<int>  pollCount { 0 };
            };

            auto shared = std::make_shared<Shared>();
            juce::uint32 teardownMs = 0;

            {
                BackgroundTaskQueue queue;

                queue.enqueue ([shared, &queue]
                {
                    // Stands in for a long HTTP request that checks for cancellation
                    // between steps. Would run for 10s if nothing interrupted it.
                    for (int i = 0; i < 1000; ++i)
                    {
                        if (queue.isStopping())
                        {
                            shared->sawStopRequest = true;
                            break;
                        }

                        ++shared->pollCount;
                        juce::Thread::sleep (10);
                    }

                    shared->finished = true;
                });

                // Let the worker get into its loop before we tear down.
                while (shared->pollCount.load() < 2)
                    juce::Thread::sleep (5);

                const auto start = juce::Time::getMillisecondCounter();
                // queue goes out of scope here — destructor runs
                (void) start;
                teardownMs = start;
            }

            teardownMs = juce::Time::getMillisecondCounter() - teardownMs;

            expect (shared->sawStopRequest.load(), "the task never observed isStopping()");
            expect (shared->finished.load(), "the task did not finish before teardown returned");
            expect (teardownMs < 1000,
                    "teardown took " + juce::String ((int) teardownMs)
                        + "ms — a cooperating task should let it return almost immediately");
        }

        beginTest ("callOnMessageThread delivers on the message thread");
        {
            // Shared state, not stack references: if the callback is late it
            // still fires after this scope exits, and must not touch dead locals.
            struct Observed
            {
                std::atomic<bool> delivered { false };
                std::atomic<bool> onMessageThread { false };
                std::atomic<bool> workerWasMessageThread { true };
            };

            auto observed = std::make_shared<Observed>();
            auto* mm = juce::MessageManager::getInstance();

            {
                BackgroundTaskQueue queue;

                queue.enqueue ([observed, mm]
                {
                    // A background worker is, by definition, not the message thread.
                    observed->workerWasMessageThread = mm->isThisTheMessageThread();

                    BackgroundTaskQueue::callOnMessageThread ([observed, mm]
                    {
                        observed->onMessageThread = mm->isThisTheMessageThread();
                        observed->delivered = true;
                    });
                });

                expect (queue.waitForAll (5000), "queue did not drain");
            }

            // Pump the message loop until the async callback lands.
            const auto start = juce::Time::getMillisecondCounter();
            while (! observed->delivered.load()
                   && (juce::uint32) (juce::Time::getMillisecondCounter() - start) < 5000)
                mm->runDispatchLoopUntil (10);

            expect (observed->delivered.load(), "callback was never delivered");
            expect (! observed->workerWasMessageThread.load(), "the worker ran on the message thread");
            expect (observed->onMessageThread.load(), "callback did not run on the message thread");
        }
    }
};

static BackgroundTaskQueueTests backgroundTaskQueueTests;

} // namespace acemusic
