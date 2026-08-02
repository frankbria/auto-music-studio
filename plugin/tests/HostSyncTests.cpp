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

        //======================================================================
        // US-24.2 — the host's loop / cycle range as a selection.

        beginTest ("AC: bars 5-13 at 120 BPM 4/4 is a 16 second selection");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            playHead.timeSigNumerator = 4;
            playHead.timeSigDenominator = 4;

            // Bar 5 starts after 4 bars = 16 quarter notes; bar 13 after 48.
            playHead.loopStartPpq = 16.0;
            playHead.loopEndPpq = 48.0;

            sync.captureFrom (&playHead);

            const auto selection = HostSync::describeSelection (sync.get());

            expect (selection.present, "the loop range was not seen");
            expect (selection.hasLength);
            expect (selection.hasBars);

            // 32 quarter notes at 120 BPM = 32 * 0.5s = 16s. This is the story's example.
            expectWithinAbsoluteError (selection.lengthSeconds, 16.0, 1.0e-9);
            expectWithinAbsoluteError (selection.startBar, 5.0, 1.0e-9);
            expectWithinAbsoluteError (selection.endBar, 13.0, 1.0e-9);
        }

        beginTest ("bar arithmetic follows the time signature, not a hardcoded 4/4");
        {
            const auto barsFor = [] (int numerator, int denominator, double ppq)
            {
                HostSync::Snapshot snapshot;
                snapshot.bpm = 120.0;
                snapshot.timeSigNumerator = numerator;
                snapshot.timeSigDenominator = denominator;
                snapshot.loopStartPpq = ppq;
                snapshot.loopEndPpq = ppq + 4.0;
                return HostSync::describeSelection (snapshot).startBar;
            };

            // 3/4: 3 quarter notes to the bar, so bar 3 starts at 6 quarter notes.
            expectWithinAbsoluteError (barsFor (3, 4, 6.0), 3.0, 1.0e-9);

            // 6/8: 6 eighths = 3 quarter notes to the bar. Same maths, different route.
            expectWithinAbsoluteError (barsFor (6, 8, 6.0), 3.0, 1.0e-9);

            // 7/8: 3.5 quarter notes to the bar.
            expectWithinAbsoluteError (barsFor (7, 8, 7.0), 3.0, 1.0e-9);

            // 4/4 sanity: bar 1 is at 0, not bar 0.
            expectWithinAbsoluteError (barsFor (4, 4, 0.0), 1.0, 1.0e-9);
        }

        beginTest ("a selection with no tempo has no length, rather than a length of zero");
        {
            HostSync::Snapshot snapshot;
            snapshot.bpm = 0.0;                 // host publishes no tempo
            snapshot.loopStartPpq = 16.0;
            snapshot.loopEndPpq = 48.0;
            snapshot.timeSigNumerator = 4;
            snapshot.timeSigDenominator = 4;

            const auto selection = HostSync::describeSelection (snapshot);

            expect (selection.present, "the range itself is still known");
            expect (! selection.hasLength, "an unknowable length was reported as known");
            expectEquals (selection.lengthSeconds, 0.0);

            // The bars do not depend on tempo, so they are still available.
            expect (selection.hasBars);
            expectWithinAbsoluteError (selection.startBar, 5.0, 1.0e-9);
        }

        beginTest ("a selection with no time signature still has a length");
        {
            HostSync::Snapshot snapshot;
            snapshot.bpm = 120.0;
            snapshot.loopStartPpq = 16.0;
            snapshot.loopEndPpq = 48.0;
            // no time signature reported

            const auto selection = HostSync::describeSelection (snapshot);

            expect (selection.present);
            expect (selection.hasLength);
            expectWithinAbsoluteError (selection.lengthSeconds, 16.0, 1.0e-9);
            expect (! selection.hasBars, "bars were invented without a time signature");
        }

        beginTest ("AC: no selection is reported when the host has no loop range");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            playHead.timeSigNumerator = 4;
            playHead.timeSigDenominator = 4;
            // loopStartPpq == loopEndPpq == 0: no cycle locators set

            sync.captureFrom (&playHead);

            const auto selection = HostSync::describeSelection (sync.get());
            expect (! selection.present, "a selection was invented from an empty loop range");
            expect (! selection.hasLength);
            expect (! selection.hasBars);
        }

        beginTest ("clearing the loop range in the host clears the selection");
        {
            HostSync sync;
            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            playHead.loopStartPpq = 16.0;
            playHead.loopEndPpq = 48.0;

            sync.captureFrom (&playHead);
            expect (HostSync::describeSelection (sync.get()).present);

            playHead.loopStartPpq = 0.0;
            playHead.loopEndPpq = 0.0;
            sync.captureFrom (&playHead);

            expect (! HostSync::describeSelection (sync.get()).present,
                    "a stale selection survived the host clearing its loop range");
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
