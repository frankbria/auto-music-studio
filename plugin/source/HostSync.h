#pragma once

#include <juce_audio_basics/juce_audio_basics.h>

#include <atomic>

namespace acemusic
{

/**
    The host's transport, read once on the audio thread and published to everyone else.

    `juce::AudioProcessor::getPlayHead()` is an **audio thread** API: the pointer the
    host installs is only guaranteed valid inside `processBlock`, and `getPosition()`
    on a VST3 host reads state the host updates per block. Reading it from a timer —
    which is what the results panel used to do for its playhead readout — is a data
    race that happens to work most of the time.

    So there is exactly one reader, in `processBlock`, and everything else takes a
    snapshot from here.

    **What the host does not tell us.** JUCE 8's `AudioPlayHead::PositionInfo` carries
    tempo, time signature, PPQ and the transport flags — and *no key signature*. The
    only key-signature channel in JUCE is ARA (`kARAContentTypeKeySignatures`), a
    separate Celemony-licensed SDK that a handful of hosts implement. Key therefore
    cannot be synced from the host through VST3, AU or Standalone, and the generation
    panel leaves that field manual rather than implying a sync that is not happening.
*/
class HostSync
{
public:
    /** What the host reported as of the last audio block. */
    struct Snapshot
    {
        /** Host tempo, or 0 when the host reports none — which is the normal case in
            the Standalone build and in hosts that do not publish a tempo. Nothing
            silently substitutes 120 for it. */
        double bpm = 0.0;

        /** Transport position, or < 0 when the host reports none. */
        double timeInSeconds = -1.0;

        /** The host's loop / cycle range in quarter notes. `loopEndPpq > loopStartPpq`
            is what makes it a range; equal values mean the host reports none.

            This is the **cycle locators**, not an arbitrary time selection — VST3 has no
            API for the latter. In Reaper the loop range is linked to the time selection
            by default; in Cubase and Logic these are the cycle markers. */
        double loopStartPpq = 0.0;
        double loopEndPpq = 0.0;

        /** Time signature, or 0/0 when the host reports none. Needed to turn a position
            in quarter notes into a bar number. */
        int timeSigNumerator = 0;
        int timeSigDenominator = 0;

        bool hasBpm() const noexcept                          { return bpm > 0.0; }
        bool hasTime() const noexcept                         { return timeInSeconds >= 0.0; }
        bool hasLoop() const noexcept                         { return loopEndPpq > loopStartPpq; }
        bool hasTimeSignature() const noexcept                { return timeSigNumerator > 0 && timeSigDenominator > 0; }
    };

    /** The host's loop range, in the terms the generation panel shows it.

        Derived rather than stored, because it needs two other things the host reports
        separately: the length in seconds needs the tempo, and the bar numbers need the
        time signature. Either being absent is a real state the UI has to render — a
        selection whose length is unknown must not read as "0.0s". */
    struct Selection
    {
        /** True when the host reports a loop range at all. */
        bool present = false;

        /** True when the length in seconds is known, i.e. the host also reports a tempo. */
        bool hasLength = false;

        /** True when the bar numbers are known, i.e. the host also reports a time signature. */
        bool hasBars = false;

        double lengthSeconds = 0.0;

        /** 1-based, the way every DAW displays bars. */
        double startBar = 1.0;
        double endBar = 1.0;
    };

    /** Interprets `snapshot`'s loop range. Pure — exposed so it can be tested without a host. */
    static Selection describeSelection (const Snapshot& snapshot) noexcept;

    /** A bar number as a DAW would show it: "5", or "5.5" when the range does not start
        on a bar line. Shared so the generation and results panels cannot disagree. */
    static juce::String formatBar (double bar);

    /** Publishes `playHead`'s position. Audio thread: allocates nothing, takes no
        locks, and tolerates a null play head (the host gave us none). */
    void captureFrom (juce::AudioPlayHead* playHead) noexcept;

    /** The last published position. Safe from any thread. */
    Snapshot get() const noexcept;

private:
    // Separate atomics rather than one packed struct, which would not be lock-free.
    // The only cost is that a reader can catch the previous block's tempo beside this
    // block's clock — invisible when the UI refreshes at 2Hz, and cheaper than a lock
    // the audio thread would have to take.
    std::atomic<double> bpm { 0.0 };
    std::atomic<double> timeInSeconds { -1.0 };
    std::atomic<double> loopStartPpq { 0.0 };
    std::atomic<double> loopEndPpq { 0.0 };
    std::atomic<int> timeSigNumerator { 0 };
    std::atomic<int> timeSigDenominator { 0 };
};

} // namespace acemusic
