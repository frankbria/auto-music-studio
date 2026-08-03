#include "MidiCapture.h"
#include "AudioIo.h"

#include <cmath>

namespace acemusic
{

namespace
{
    /** Short attack and release on every rendered note. Without them each note starts
        and ends on a discontinuity, and a reference full of clicks describes the clicks
        as much as the melody. */
    constexpr double envelopeSeconds = 0.005;

    /** Notes still held when recording stops are given this much tail rather than being
        thrown away — a held final chord is usually the point of the take. */
    constexpr double unfinishedNoteSeconds = 0.5;
}

void MidiCapture::prepare (double sampleRate)
{
    if (sampleRate > 0.0)
        preparedSampleRate = sampleRate;
}

void MidiCapture::processBlock (const juce::MidiBuffer& midi, int numSamples) noexcept
{
    if (! recording.load (std::memory_order_relaxed))
        return;

    const auto blockStart = position.load (std::memory_order_relaxed);

    for (const auto metadata : midi)
    {
        const auto message = metadata.getMessage();

        if (! message.isNoteOnOrOff())
            continue;

        int start1 = 0, size1 = 0, start2 = 0, size2 = 0;
        fifo.prepareToWrite (1, start1, size1, start2, size2);

        if (size1 + size2 < 1)
        {
            // Full. Dropping is the only option that does not allocate here; the count
            // is surfaced so the take is not silently reported as complete.
            dropped.fetch_add (1, std::memory_order_relaxed);
            continue;
        }

        auto& event = events[(size_t) (size1 > 0 ? start1 : start2)];
        event.sample = blockStart + metadata.samplePosition;
        event.noteNumber = message.getNoteNumber();
        event.velocity = message.getFloatVelocity();
        // A note-on at velocity 0 is a note-off; juce::MidiMessage already knows this.
        event.isNoteOn = message.isNoteOn();

        fifo.finishedWrite (1);
    }

    position.store (blockStart + numSamples, std::memory_order_relaxed);
}

void MidiCapture::setRecording (bool shouldRecord)
{
    if (shouldRecord == recording.load())
        return;

    if (shouldRecord)
    {
        // A new take replaces the old one rather than appending to it.
        clear();
        recording.store (true);
    }
    else
    {
        recording.store (false);
        drain();
    }
}

void MidiCapture::drain()
{
    int start1 = 0, size1 = 0, start2 = 0, size2 = 0;
    fifo.prepareToRead (fifo.getNumReady(), start1, size1, start2, size2);

    const auto consume = [this] (int start, int size)
    {
        for (int i = 0; i < size; ++i)
        {
            const auto& event = events[(size_t) (start + i)];

            if (event.isNoteOn)
            {
                notes.push_back ({ event.noteNumber, event.velocity, event.sample, -1 });
                continue;
            }

            // Close the most recent open note of the same pitch. Searching backwards
            // matters for repeated notes: the newest one is the one being released.
            for (auto note = notes.rbegin(); note != notes.rend(); ++note)
            {
                if (note->noteNumber == event.noteNumber && note->endSample < 0)
                {
                    note->endSample = event.sample;
                    break;
                }
            }
        }
    };

    consume (start1, size1);
    consume (start2, size2);

    fifo.finishedRead (size1 + size2);
}

double MidiCapture::getLengthSeconds() const
{
    juce::int64 last = 0;

    for (const auto& note : notes)
    {
        last = juce::jmax (last, note.isFinished()
                                     ? note.endSample
                                     : note.startSample + (juce::int64) (unfinishedNoteSeconds * preparedSampleRate));
    }

    return (double) last / preparedSampleRate;
}

void MidiCapture::clear()
{
    notes.clear();
    position.store (0);
    dropped.store (0);

    int start1 = 0, size1 = 0, start2 = 0, size2 = 0;
    fifo.prepareToRead (fifo.getNumReady(), start1, size1, start2, size2);
    fifo.finishedRead (size1 + size2);
}

juce::AudioBuffer<float> MidiCapture::render() const
{
    const auto lengthSeconds = getLengthSeconds();

    if (notes.empty() || lengthSeconds <= 0.0)
        return {};

    const auto numSamples = (int) std::ceil (lengthSeconds * preparedSampleRate);
    juce::AudioBuffer<float> buffer (1, numSamples);
    buffer.clear();

    auto* out = buffer.getWritePointer (0);
    const auto envelopeSamples = juce::jmax (1, (int) (envelopeSeconds * preparedSampleRate));

    for (const auto& note : notes)
    {
        const auto start = (int) note.startSample;
        const auto end = (int) (note.isFinished()
                                    ? note.endSample
                                    : note.startSample + (juce::int64) (unfinishedNoteSeconds * preparedSampleRate));

        if (start >= numSamples || end <= start)
            continue;

        const auto last = juce::jmin (end, numSamples);
        const auto frequency = juce::MidiMessage::getMidiNoteInHertz (note.noteNumber);
        const auto increment = juce::MathConstants<double>::twoPi * frequency / preparedSampleRate;

        // Velocity-scaled, and headroom for the overlap of a chord: several notes
        // sounding at once must not sum past full scale.
        const auto gain = 0.2f * juce::jlimit (0.05f, 1.0f, note.velocity);

        for (int i = start; i < last; ++i)
        {
            const auto into = i - start;
            const auto remaining = last - i;

            const auto envelope = juce::jmin (1.0f,
                                              (float) into / (float) envelopeSamples,
                                              (float) remaining / (float) envelopeSamples);

            out[i] += gain * envelope * (float) std::sin (increment * (double) into);
        }
    }

    // A dense chord can still stack past 1.0; scale the whole take rather than clipping
    // individual notes, which would change their relative levels.
    const auto peak = buffer.getMagnitude (0, numSamples);

    if (peak > 1.0f)
        buffer.applyGain (1.0f / peak);

    return buffer;
}

bool MidiCapture::writeTo (const juce::File& destination) const
{
    const auto rendered = render();

    if (rendered.getNumSamples() <= 0)
        return false;

    return AudioIo::writeWav (destination, rendered, preparedSampleRate);
}

} // namespace acemusic
