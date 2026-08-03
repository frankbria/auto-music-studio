#include "HostSync.h"

namespace acemusic
{

void HostSync::captureFrom (juce::AudioPlayHead* playHead) noexcept
{
    // A host that stops reporting should clear the fields rather than leave the last
    // values frozen on screen, so every field is written on every path below.
    double newBpm = 0.0;
    double newTime = -1.0;
    double newLoopStart = 0.0;
    double newLoopEnd = 0.0;
    int newNumerator = 0;
    int newDenominator = 0;

    if (playHead != nullptr)
    {
        if (const auto position = playHead->getPosition())
        {
            if (const auto hostBpm = position->getBpm())
                newBpm = *hostBpm;

            if (const auto seconds = position->getTimeInSeconds())
                newTime = *seconds;

            if (const auto loop = position->getLoopPoints())
            {
                newLoopStart = loop->ppqStart;
                newLoopEnd = loop->ppqEnd;
            }

            if (const auto signature = position->getTimeSignature())
            {
                newNumerator = signature->numerator;
                newDenominator = signature->denominator;
            }
        }
    }

    bpm.store (newBpm, std::memory_order_relaxed);
    timeInSeconds.store (newTime, std::memory_order_relaxed);
    loopStartPpq.store (newLoopStart, std::memory_order_relaxed);
    loopEndPpq.store (newLoopEnd, std::memory_order_relaxed);
    timeSigNumerator.store (newNumerator, std::memory_order_relaxed);
    timeSigDenominator.store (newDenominator, std::memory_order_relaxed);
}

HostSync::Selection HostSync::describeSelection (const Snapshot& snapshot) noexcept
{
    Selection selection;

    if (! snapshot.hasLoop())
        return selection;

    selection.present = true;

    if (snapshot.hasBpm())
    {
        selection.hasLength = true;
        // A quarter note is 60/bpm seconds, and the loop range is measured in them.
        selection.lengthSeconds = (snapshot.loopEndPpq - snapshot.loopStartPpq) * 60.0 / snapshot.bpm;
    }

    if (snapshot.hasTimeSignature())
    {
        // 4/4 is 4 quarter notes to the bar, 6/8 is 3, 3/4 is 3.
        const auto quarterNotesPerBar = (double) snapshot.timeSigNumerator * 4.0
                                            / (double) snapshot.timeSigDenominator;

        if (quarterNotesPerBar > 0.0)
        {
            selection.hasBars = true;
            // +1 because DAWs number the first bar 1, not 0.
            selection.startBar = snapshot.loopStartPpq / quarterNotesPerBar + 1.0;
            selection.endBar   = snapshot.loopEndPpq / quarterNotesPerBar + 1.0;
        }
    }

    return selection;
}

juce::String HostSync::formatBar (double bar)
{
    // Two decimals, then the trailing zeros and any bare point trimmed off, so a bar
    // line reads "5" rather than "5.00" but an off-grid range still reads "5.25".
    return juce::String (bar, 2).trimCharactersAtEnd ("0").trimCharactersAtEnd (".");
}

HostSync::Snapshot HostSync::get() const noexcept
{
    Snapshot snapshot;
    snapshot.bpm = bpm.load (std::memory_order_relaxed);
    snapshot.timeInSeconds = timeInSeconds.load (std::memory_order_relaxed);
    snapshot.loopStartPpq = loopStartPpq.load (std::memory_order_relaxed);
    snapshot.loopEndPpq = loopEndPpq.load (std::memory_order_relaxed);
    snapshot.timeSigNumerator = timeSigNumerator.load (std::memory_order_relaxed);
    snapshot.timeSigDenominator = timeSigDenominator.load (std::memory_order_relaxed);
    return snapshot;
}

} // namespace acemusic
