#include "MidiCapture.h"
#include "SidechainCapture.h"

#include <cmath>

namespace acemusic
{

/** MidiCapture and SidechainCapture: the two things US-24.3 feeds the server with. */
class CaptureTests final : public juce::UnitTest
{
public:
    CaptureTests()
        : juce::UnitTest ("Capture", "acemusic")
    {
    }

    static constexpr double sampleRate = 44100.0;

    /** A note-on and its note-off, `lengthSamples` apart, delivered across blocks. */
    static void playNote (MidiCapture& capture, int noteNumber, int startSample,
                          int lengthSamples, int blockSize = 512, float velocity = 0.8f)
    {
        const auto endSample = startSample + lengthSamples;

        for (int block = 0; block * blockSize < endSample + blockSize; ++block)
        {
            const auto blockStart = block * blockSize;
            juce::MidiBuffer midi;

            if (startSample >= blockStart && startSample < blockStart + blockSize)
                midi.addEvent (juce::MidiMessage::noteOn (1, noteNumber, velocity),
                               startSample - blockStart);

            if (endSample >= blockStart && endSample < blockStart + blockSize)
                midi.addEvent (juce::MidiMessage::noteOff (1, noteNumber),
                               endSample - blockStart);

            capture.processBlock (midi, blockSize);
        }
    }

    static double estimateFrequency (const juce::AudioBuffer<float>& buffer, int from, int to)
    {
        const auto* data = buffer.getReadPointer (0);
        int crossings = 0;

        for (int i = from + 1; i < to; ++i)
            if ((data[i - 1] < 0.0f) != (data[i] < 0.0f))
                ++crossings;

        return (double) crossings / 2.0 / ((double) (to - from) / sampleRate);
    }

    void runTest() override
    {
        //======================================================================
        beginTest ("nothing is captured until recording is armed");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);

            playNote (capture, 69, 0, 4410);
            capture.drain();

            expect (! capture.hasCapture(), "captured MIDI without being armed");
            expect (capture.getNotes().empty());
        }

        beginTest ("AC: playing MIDI into the plugin captures it");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            playNote (capture, 69, 1000, 22050);      // A4, half a second
            capture.setRecording (false);              // stopping drains

            expect (capture.hasCapture(), "nothing was captured");
            expectEquals ((int) capture.getNotes().size(), 1);

            const auto& note = capture.getNotes().front();
            expectEquals (note.noteNumber, 69);
            expect (note.isFinished(), "the note-off never landed");
            expectEquals ((int) note.startSample, 1000);
            expectEquals ((int) note.endSample, 1000 + 22050);
            expectWithinAbsoluteError (note.velocity, 0.8f, 0.02f);
        }

        beginTest ("a chord captures every note, and repeats close the right one");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            // C major triad held together.
            juce::MidiBuffer on;
            on.addEvent (juce::MidiMessage::noteOn (1, 60, 0.7f), 0);
            on.addEvent (juce::MidiMessage::noteOn (1, 64, 0.7f), 0);
            on.addEvent (juce::MidiMessage::noteOn (1, 67, 0.7f), 0);
            capture.processBlock (on, 512);

            for (int i = 0; i < 10; ++i)
                capture.processBlock ({}, 512);

            juce::MidiBuffer off;
            off.addEvent (juce::MidiMessage::noteOff (1, 60), 0);
            off.addEvent (juce::MidiMessage::noteOff (1, 64), 0);
            off.addEvent (juce::MidiMessage::noteOff (1, 67), 0);
            capture.processBlock (off, 512);

            capture.setRecording (false);

            expectEquals ((int) capture.getNotes().size(), 3);

            for (const auto& note : capture.getNotes())
                expect (note.isFinished(), "note " + juce::String (note.noteNumber) + " never closed");
        }

        beginTest ("a note-on at velocity 0 is treated as a note-off");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            juce::MidiBuffer midi;
            midi.addEvent (juce::MidiMessage::noteOn (1, 60, 0.8f), 0);
            capture.processBlock (midi, 512);

            juce::MidiBuffer running;
            // Running-status note-off: note-on with velocity 0. Sequencers emit these.
            running.addEvent (juce::MidiMessage::noteOn (1, 60, (juce::uint8) 0), 0);
            capture.processBlock (running, 512);

            capture.setRecording (false);

            expectEquals ((int) capture.getNotes().size(), 1);
            expect (capture.getNotes().front().isFinished(),
                    "a velocity-0 note-on did not close the note");
        }

        beginTest ("re-arming replaces the previous take rather than appending to it");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);

            capture.setRecording (true);
            playNote (capture, 60, 0, 4410);
            capture.setRecording (false);
            expectEquals ((int) capture.getNotes().size(), 1);

            capture.setRecording (true);
            playNote (capture, 72, 0, 4410);
            capture.setRecording (false);

            expectEquals ((int) capture.getNotes().size(), 1);
            expectEquals (capture.getNotes().front().noteNumber, 72,
                          "the second take was appended to the first");
        }

        beginTest ("AC: the render carries the pitch and the rhythm of the performance");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            // A4 (440Hz) for half a second, starting a quarter second in.
            playNote (capture, 69, 11025, 22050);
            capture.setRecording (false);

            const auto rendered = capture.render();
            expect (rendered.getNumSamples() > 0, "nothing was rendered");

            // Silence before the note...
            const auto before = rendered.getMagnitude (0, 0, 11000);
            expectWithinAbsoluteError (before, 0.0f, 1.0e-4f,
                                       "sound where the performance was silent");

            // ...sound during it...
            const auto during = rendered.getMagnitude (0, 12000, 20000);
            expect (during > 0.01f, "the note did not sound: magnitude " + juce::String (during));

            // ...and the pitch is A440, not some other note.
            const auto frequency = estimateFrequency (rendered, 12000, 32000);
            expectWithinAbsoluteError (frequency, 440.0, 5.0,
                                       "rendered at " + juce::String (frequency) + "Hz, expected 440");
        }

        beginTest ("a chord renders without clipping");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            juce::MidiBuffer on;
            for (auto note : { 60, 64, 67, 72, 76 })
                on.addEvent (juce::MidiMessage::noteOn (1, note, 1.0f), 0);

            capture.processBlock (on, 512);

            for (int i = 0; i < 40; ++i)
                capture.processBlock ({}, 512);

            juce::MidiBuffer off;
            for (auto note : { 60, 64, 67, 72, 76 })
                off.addEvent (juce::MidiMessage::noteOff (1, note), 0);

            capture.processBlock (off, 512);
            capture.setRecording (false);

            const auto rendered = capture.render();
            expect (rendered.getNumSamples() > 0);
            expect (rendered.getMagnitude (0, rendered.getNumSamples()) <= 1.0f,
                    "five notes at full velocity clipped");
        }

        beginTest ("a note still held when recording stops is not thrown away");
        {
            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);

            juce::MidiBuffer on;
            on.addEvent (juce::MidiMessage::noteOn (1, 60, 0.9f), 0);
            capture.processBlock (on, 512);
            capture.setRecording (false);   // never released

            expectEquals ((int) capture.getNotes().size(), 1);
            expect (! capture.getNotes().front().isFinished());
            expect (capture.getLengthSeconds() > 0.0, "a held note gave the take no length");
            expect (capture.render().getNumSamples() > 0, "a held note rendered nothing");
        }

        beginTest ("writing produces a readable WAV");
        {
            ScopedTempDir dir;

            MidiCapture capture;
            capture.prepare (sampleRate);
            capture.setRecording (true);
            playNote (capture, 69, 0, 22050);
            capture.setRecording (false);

            const auto file = dir.directory.getChildFile ("nested").getChildFile ("sketch.wav");
            expect (capture.writeTo (file), "the write failed");
            expect (file.existsAsFile(), "no file was created");

            juce::AudioFormatManager formats;
            formats.registerBasicFormats();
            std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (file));

            expect (reader != nullptr, "what was written is not readable audio");
            expectWithinAbsoluteError (reader->sampleRate, sampleRate, 0.5);
            expect (reader->lengthInSamples > 0);

            // An empty capture writes nothing rather than an empty file.
            MidiCapture empty;
            empty.prepare (sampleRate);
            expect (! empty.writeTo (dir.directory.getChildFile ("empty.wav")));
            expect (! dir.directory.getChildFile ("empty.wav").existsAsFile());
        }

        //======================================================================
        beginTest ("AC: sidechain audio is captured and round-trips");
        {
            SidechainCapture capture;
            capture.prepare (sampleRate, 2);
            capture.setRecording (true);

            juce::AudioBuffer<float> block (2, 512);

            for (int b = 0; b < 20; ++b)
            {
                for (int channel = 0; channel < 2; ++channel)
                    for (int i = 0; i < 512; ++i)
                        block.setSample (channel, i,
                                         0.5f * std::sin (juce::MathConstants<float>::twoPi
                                                          * 220.0f * (float) (b * 512 + i) / (float) sampleRate));

                capture.processBlock (block);
            }

            capture.setRecording (false);

            expect (capture.hasCapture(), "nothing was captured");
            expectEquals ((int) capture.getRecordedSamples(), 20 * 512);
            expect (! capture.isFull(), "a short take reported the buffer as full");

            const auto captured = capture.getCapturedAudio();
            expectEquals (captured.getNumSamples(), 20 * 512);
            expectEquals (captured.getNumChannels(), 2);
            expect (captured.getMagnitude (0, captured.getNumSamples()) > 0.4f,
                    "the captured audio is not the signal that went in");
        }

        beginTest ("the sidechain is not captured unless armed");
        {
            SidechainCapture capture;
            capture.prepare (sampleRate, 2);

            juce::AudioBuffer<float> block (2, 512);
            block.clear();
            block.setSample (0, 0, 0.9f);
            capture.processBlock (block);

            expect (! capture.hasCapture(), "captured without being armed");
        }

        beginTest ("the take stops at the buffer bound rather than wrapping");
        {
            SidechainCapture capture;
            // A deliberately tiny buffer: prepare() sizes it from maxSeconds, so this
            // drives the same path a two-minute overrun would, in a fraction of a second.
            capture.prepare (64.0, 1);   // 64 * maxSeconds samples
            capture.setRecording (true);

            const auto capacity = (int) (64.0 * (double) SidechainCapture::maxSeconds);

            juce::AudioBuffer<float> block (1, capacity);
            block.clear();
            for (int i = 0; i < capacity; ++i)
                block.setSample (0, i, 0.5f);

            capture.processBlock (block);            // exactly fills it
            capture.processBlock (block);            // and this must not wrap

            expect (capture.isFull(), "the bound was not reported");
            expect (! capture.isRecording(), "recording continued past the bound");
            expectEquals ((int) capture.getRecordedSamples(), capacity,
                          "the take grew past the buffer it was given");
        }

        beginTest ("a mono sidechain fills both channels rather than leaving one stale");
        {
            SidechainCapture capture;
            capture.prepare (sampleRate, 2);
            capture.setRecording (true);

            juce::AudioBuffer<float> mono (1, 512);
            for (int i = 0; i < 512; ++i)
                mono.setSample (0, i, 0.6f);

            capture.processBlock (mono);
            capture.setRecording (false);

            const auto captured = capture.getCapturedAudio();
            expectEquals (captured.getNumChannels(), 2);
            expectWithinAbsoluteError (captured.getSample (1, 10), 0.6f, 1.0e-4f,
                                       "the second channel was not filled from the mono source");
        }

        beginTest ("re-arming the sidechain discards the previous take");
        {
            SidechainCapture capture;
            capture.prepare (sampleRate, 1);

            juce::AudioBuffer<float> block (1, 512);
            block.clear();

            capture.setRecording (true);
            capture.processBlock (block);
            capture.processBlock (block);
            capture.setRecording (false);
            expectEquals ((int) capture.getRecordedSamples(), 1024);

            capture.setRecording (true);
            capture.processBlock (block);
            capture.setRecording (false);
            expectEquals ((int) capture.getRecordedSamples(), 512,
                          "the second take was appended to the first");
        }

        beginTest ("the transport position at the start of a take is remembered");
        {
            SidechainCapture capture;
            capture.prepare (sampleRate, 1);

            expect (capture.getTransportStartSeconds() < 0.0, "invented a start position");

            capture.setRecording (true, 12.5);
            expectWithinAbsoluteError (capture.getTransportStartSeconds(), 12.5, 1.0e-9);
        }
    }

private:
    struct ScopedTempDir
    {
        ScopedTempDir()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-capture-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
        }

        ~ScopedTempDir()    { directory.deleteRecursively(); }

        juce::File directory;
    };
};

static CaptureTests captureTests;

} // namespace acemusic
