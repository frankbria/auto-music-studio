#include "FakePlayHead.h"
#include "HostSync.h"

namespace acemusic
{

class HostSyncTests final : public juce::UnitTest
{
public:
    HostSyncTests()
        : juce::UnitTest ("HostSync", "acemusic")
    {
    }

    void runTest() override
    {
        beginTest ("nothing is reported until a block has been processed");
        {
            HostSync sync;

            const auto snapshot = sync.get();
            expect (! snapshot.hasBpm(), "invented a tempo before seeing the host");
            expect (! snapshot.hasTime());
        }

        beginTest ("AC: the host tempo is picked up from the play head");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            playHead.timeInSeconds = 4.5;

            sync.captureFrom (&playHead);

            const auto snapshot = sync.get();
            expect (snapshot.hasBpm());
            expectEquals (snapshot.bpm, 120.0);
            expect (snapshot.hasTime());
            expectEquals (snapshot.timeInSeconds, 4.5);
        }

        beginTest ("AC: a tempo change on the host is picked up");
        {
            HostSync sync;
            test::FakePlayHead playHead;

            playHead.bpm = 120.0;
            sync.captureFrom (&playHead);
            expectEquals (sync.get().bpm, 120.0);

            playHead.bpm = 90.0;
            sync.captureFrom (&playHead);
            expectEquals (sync.get().bpm, 90.0, "the tempo change was not seen");
        }

        beginTest ("a host that stops reporting clears the tempo instead of freezing it");
        {
            HostSync sync;
            test::FakePlayHead playHead;

            playHead.bpm = 128.0;
            sync.captureFrom (&playHead);
            expect (sync.get().hasBpm());

            playHead.reportsPosition = false;
            sync.captureFrom (&playHead);
            expect (! sync.get().hasBpm(), "a stale tempo survived the host going quiet");
            expect (! sync.get().hasTime());
        }

        beginTest ("no play head at all is not a tempo of zero-and-a-bit");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            sync.captureFrom (&playHead);

            sync.captureFrom (nullptr);

            const auto snapshot = sync.get();
            expect (! snapshot.hasBpm());
            expect (! snapshot.hasTime());
        }

        beginTest ("a host reporting a position but no tempo is not a tempo of 0");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            playHead.bpm = 0.0;              // absent
            playHead.timeInSeconds = 12.0;

            sync.captureFrom (&playHead);

            const auto snapshot = sync.get();
            expect (! snapshot.hasBpm(), "an absent tempo read as present");
            expect (snapshot.hasTime(), "the position was lost with the tempo");
            expectEquals (snapshot.timeInSeconds, 12.0);
        }
    }
};

static HostSyncTests hostSyncTests;

} // namespace acemusic
