#pragma once

#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_audio_formats/juce_audio_formats.h>

#include <array>
#include <atomic>
#include <vector>

namespace acemusic
{

/**
    Records MIDI played into the plugin, and renders it to audio for submission.

    **Why it renders to audio at all.** ACE-Step has no MIDI input — its task types are
    text2music / cover / repaint / extract / lego / complete / mashup, and `complete`,
    the mode this feeds, takes `src_audio_path`. There is not one reference to MIDI in
    the whole ACE-Step source. So a MIDI sketch can only reach the model as *audio*, and
    this is what turns one into the other. The rendered tone is a description of the
    performance — pitch and rhythm — not an attempt to sound good.

    **Nothing is synthesised on the audio thread.** `processBlock` only pushes note
    events into a lock-free FIFO. Draining, rendering and writing all happen on the
    message thread, when the user stops recording. That is far less machinery than a
    live juce::Synthesiser, and the audio callback keeps allocating nothing.
*/
class MidiCapture
{
public:
    MidiCapture() = default;

    /** One note, as captured. Times are in samples from the start of the recording. */
    struct Note
    {
        int noteNumber = 0;
        float velocity = 0.0f;
        juce::int64 startSample = 0;

        /** < 0 while the note is still held — i.e. no note-off has arrived yet. */
        juce::int64 endSample = -1;

        bool isFinished() const noexcept                      { return endSample > startSample; }
    };

    //==============================================================================
    /** From prepareToPlay. Message thread. */
    void prepare (double sampleRate);

    /** Audio thread. Pushes any note events in `midi` into the FIFO when recording, and
        advances the recording clock. Allocates nothing and never blocks; events beyond
        the FIFO's capacity are dropped rather than growing it (see getDroppedCount). */
    void processBlock (const juce::MidiBuffer& midi, int numSamples) noexcept;

    //==============================================================================
    /** Starts or stops recording. Starting clears whatever was captured before, so a
        second take replaces the first rather than appending to it. Message thread. */
    void setRecording (bool shouldRecord);

    bool isRecording() const noexcept                         { return recording.load(); }

    /** Moves everything the audio thread has pushed into the note list. Message thread;
        cheap, and safe to call on a timer. */
    void drain();

    /** Notes captured, oldest first. Call drain() first. */
    const std::vector<Note>& getNotes() const noexcept        { return notes; }

    /** True when there is something worth submitting. */
    bool hasCapture() const noexcept                          { return ! notes.empty(); }

    /** How long the capture runs, in seconds. */
    double getLengthSeconds() const;

    /** Events the FIFO could not hold. Non-zero means the capture is incomplete, and
        the UI says so rather than pretending the take was clean. */
    int getDroppedCount() const noexcept                      { return dropped.load(); }

    void clear();

    //==============================================================================
    /** Renders the captured notes to audio. Message thread — allocates. */
    juce::AudioBuffer<float> render() const;

    /** Renders and writes a mono WAV. @returns false if nothing was captured or the
        file could not be written. */
    bool writeTo (const juce::File& destination) const;

private:
    /** What crosses the thread boundary. Kept trivially copyable and small. */
    struct Event
    {
        juce::int64 sample = 0;
        int noteNumber = 0;
        float velocity = 0.0f;
        bool isNoteOn = false;
    };

    // 4096 events is minutes of ordinary playing. A fixed capacity is the point: the
    // audio thread cannot allocate, so the choice is a bound or a leak.
    static constexpr int fifoCapacity = 4096;

    juce::AbstractFifo fifo { fifoCapacity };
    std::array<Event, (size_t) fifoCapacity> events {};

    std::atomic<bool> recording { false };
    std::atomic<int> dropped { 0 };

    /** Samples since recording started. Audio thread writes, message thread reads. */
    std::atomic<juce::int64> position { 0 };

    double preparedSampleRate = 44100.0;
    std::vector<Note> notes;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MidiCapture)
};

} // namespace acemusic
