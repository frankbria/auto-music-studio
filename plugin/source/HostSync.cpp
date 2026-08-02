#include "HostSync.h"

namespace acemusic
{

void HostSync::captureFrom (juce::AudioPlayHead* playHead) noexcept
{
    // A host that stops reporting should clear the fields rather than leave the last
    // value frozen on screen, so every path below writes both.
    double newBpm = 0.0;
    double newTime = -1.0;

    if (playHead != nullptr)
    {
        if (const auto position = playHead->getPosition())
        {
            if (const auto hostBpm = position->getBpm())
                newBpm = *hostBpm;

            if (const auto seconds = position->getTimeInSeconds())
                newTime = *seconds;
        }
    }

    bpm.store (newBpm, std::memory_order_relaxed);
    timeInSeconds.store (newTime, std::memory_order_relaxed);
}

HostSync::Snapshot HostSync::get() const noexcept
{
    Snapshot snapshot;
    snapshot.bpm = bpm.load (std::memory_order_relaxed);
    snapshot.timeInSeconds = timeInSeconds.load (std::memory_order_relaxed);
    return snapshot;
}

} // namespace acemusic
