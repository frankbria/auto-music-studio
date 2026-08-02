#pragma once

#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_audio_formats/juce_audio_formats.h>

#include <atomic>

namespace acemusic
{

/**
    Records the plugin's sidechain input, so an existing DAW track can be used as the
    reference for Cover and Repaint generation.

    The buffer is allocated once in prepare() and never grows. That is not a
    simplification to revisit: the audio thread cannot allocate, so a recording either
    has a bound or it is a hazard. Recording stops of its own accord when the buffer is
    full, and `isFull()` says so, rather than silently overwriting the take.
*/
class SidechainCapture
{
public:
    SidechainCapture() = default;

    /** How much audio a take can hold. Generated clips are up to a few minutes and a
        reference only needs to describe the material, so this is generous. */
    static constexpr int maxSeconds = 120;

    /** From prepareToPlay. Message thread — this is where the memory comes from. */
    void prepare (double sampleRate, int numChannels);

    /** Audio thread. Appends `source` while recording. Allocates nothing, never blocks,
        and stops recording rather than wrapping when the buffer fills. */
    void processBlock (const juce::AudioBuffer<float>& source) noexcept;

    //==============================================================================
    /** Starts or stops. Starting discards the previous take. Message thread.

        @param transportSecondsAtStart  where the host transport was when recording
               began, or < 0 if unknown. Repaint needs it to express the host's loop
               range as an offset into *this take* rather than into the project. */
    void setRecording (bool shouldRecord, double transportSecondsAtStart = -1.0);

    /** Host transport position when this take started, or < 0 if it was not recorded. */
    double getTransportStartSeconds() const noexcept          { return transportStart; }

    bool isRecording() const noexcept                         { return recording.load(); }

    /** True once the take hit the buffer bound and recording stopped itself. */
    bool isFull() const noexcept                              { return full.load(); }

    /** True when there is something worth submitting. */
    bool hasCapture() const noexcept                          { return getRecordedSamples() > 0; }

    juce::int64 getRecordedSamples() const noexcept           { return written.load(); }
    double getLengthSeconds() const;

    void clear();

    //==============================================================================
    /** Writes the take as a WAV. @returns false if nothing was captured or the write
        failed. Message thread. */
    bool writeTo (const juce::File& destination) const;

    /** The captured audio. Message thread; for tests and rendering. */
    juce::AudioBuffer<float> getCapturedAudio() const;

private:
    juce::AudioBuffer<float> buffer;

    std::atomic<bool> recording { false };
    std::atomic<bool> full { false };

    /** Samples written so far. Audio thread writes, message thread reads. */
    std::atomic<juce::int64> written { 0 };

    double preparedSampleRate = 44100.0;
    double transportStart = -1.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SidechainCapture)
};

} // namespace acemusic
