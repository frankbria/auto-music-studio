#include "SidechainCapture.h"
#include "AudioIo.h"

namespace acemusic
{

void SidechainCapture::prepare (double sampleRate, int numChannels)
{
    if (sampleRate <= 0.0 || numChannels <= 0)
        return;

    preparedSampleRate = sampleRate;

    // Allocated here, on the message thread, and never again.
    buffer.setSize (numChannels, (int) (sampleRate * (double) maxSeconds), false, true, false);
    clear();
}

void SidechainCapture::processBlock (const juce::AudioBuffer<float>& source) noexcept
{
    if (! recording.load (std::memory_order_relaxed))
        return;

    const auto capacity = buffer.getNumSamples();
    const auto offset = (int) written.load (std::memory_order_relaxed);
    const auto available = capacity - offset;

    if (available <= 0)
    {
        // Stop rather than wrap: overwriting the start of the take would quietly hand
        // the model the wrong reference.
        recording.store (false, std::memory_order_relaxed);
        full.store (true, std::memory_order_relaxed);
        return;
    }

    const auto toCopy = juce::jmin (available, source.getNumSamples());
    const auto channels = juce::jmin (buffer.getNumChannels(), source.getNumChannels());

    for (int channel = 0; channel < channels; ++channel)
        buffer.copyFrom (channel, offset, source, channel, 0, toCopy);

    // A mono sidechain into a stereo buffer would otherwise leave the right channel as
    // whatever the last take put there.
    for (int channel = channels; channel < buffer.getNumChannels(); ++channel)
        buffer.copyFrom (channel, offset, source, 0, 0, toCopy);

    written.store ((juce::int64) (offset + toCopy), std::memory_order_relaxed);

    if (toCopy < source.getNumSamples())
    {
        recording.store (false, std::memory_order_relaxed);
        full.store (true, std::memory_order_relaxed);
    }
}

void SidechainCapture::setRecording (bool shouldRecord, double transportSecondsAtStart)
{
    if (shouldRecord == recording.load())
        return;

    if (shouldRecord)
    {
        clear();
        transportStart = transportSecondsAtStart;
        recording.store (true);
    }
    else
    {
        recording.store (false);
    }
}

double SidechainCapture::getLengthSeconds() const
{
    return (double) written.load() / preparedSampleRate;
}

void SidechainCapture::clear()
{
    written.store (0);
    full.store (false);
    buffer.clear();
}

juce::AudioBuffer<float> SidechainCapture::getCapturedAudio() const
{
    const auto length = (int) written.load();

    if (length <= 0 || buffer.getNumChannels() <= 0)
        return {};

    juce::AudioBuffer<float> captured (buffer.getNumChannels(), length);

    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
        captured.copyFrom (channel, 0, buffer, channel, 0, length);

    return captured;
}

bool SidechainCapture::writeTo (const juce::File& destination) const
{
    const auto captured = getCapturedAudio();

    if (captured.getNumSamples() <= 0)
        return false;

    return AudioIo::writeWav (destination, captured, preparedSampleRate);
}

} // namespace acemusic
