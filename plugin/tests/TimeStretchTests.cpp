#include "TimeStretch.h"

#include <cmath>

namespace acemusic
{

class TimeStretchTests final : public juce::UnitTest
{
public:
    TimeStretchTests()
        : juce::UnitTest ("TimeStretch", "acemusic")
    {
    }

    static constexpr double sampleRate = 44100.0;

    static juce::AudioBuffer<float> makeSine (double frequency, double seconds, int channels = 2)
    {
        const int numSamples = (int) (seconds * sampleRate);
        juce::AudioBuffer<float> buffer (channels, numSamples);

        for (int channel = 0; channel < channels; ++channel)
        {
            auto* out = buffer.getWritePointer (channel);

            for (int i = 0; i < numSamples; ++i)
                out[i] = (float) (0.5 * std::sin (juce::MathConstants<double>::twoPi
                                                      * frequency * (double) i / sampleRate));
        }

        return buffer;
    }

    /** Frequency estimated from the zero-crossing rate — enough to catch a pitch shift,
        and the thing a resample-based stretch would fail. */
    static double estimateFrequency (const juce::AudioBuffer<float>& buffer)
    {
        const auto* data = buffer.getReadPointer (0);
        const int numSamples = buffer.getNumSamples();

        // The outer 10% is skipped: the first and last frames of an overlap-add are
        // partial by construction and their level is not representative.
        const int start = numSamples / 10;
        const int end = numSamples - numSamples / 10;

        int crossings = 0;

        for (int i = start + 1; i < end; ++i)
            if ((data[i - 1] < 0.0f) != (data[i] < 0.0f))
                ++crossings;

        const double seconds = (double) (end - start) / sampleRate;
        return (double) crossings / 2.0 / seconds;
    }

    void runTest() override
    {
        beginTest ("the rate matches the Python side's calculate_speed_multiplier");
        {
            // target / original — 118 to 120 speeds up slightly.
            expectWithinAbsoluteError (TimeStretch::rateFor (118.0, 120.0), 120.0 / 118.0, 1.0e-12);
            expectWithinAbsoluteError (TimeStretch::rateFor (120.0, 100.0), 100.0 / 120.0, 1.0e-12);

            // A tempo nobody knows is not a rate of 0-and-carry-on.
            expectEquals (TimeStretch::rateFor (0.0, 120.0), 0.0);
            expectEquals (TimeStretch::rateFor (120.0, 0.0), 0.0);
            expectEquals (TimeStretch::rateFor (-120.0, 120.0), 0.0);
        }

        beginTest ("tempos that agree are not worth stretching");
        {
            expect (! TimeStretch::isWorthStretching (1.0));
            expect (! TimeStretch::isWorthStretching (TimeStretch::rateFor (120.0, 120.0)));
            expect (! TimeStretch::isWorthStretching (0.0), "a rate of 0 asked to be stretched");

            // The story's own example must clear the threshold, or the feature is inert.
            expect (TimeStretch::isWorthStretching (TimeStretch::rateFor (118.0, 120.0)),
                    "118 to 120 BPM was dismissed as too small to correct");
            expect (TimeStretch::isWorthStretching (TimeStretch::rateFor (120.0, 100.0)));
        }

        beginTest ("AC: a 118 BPM clip becomes 120 BPM — the length changes by exactly the ratio");
        {
            const auto source = makeSine (440.0, 4.0);
            const auto rate = TimeStretch::rateFor (118.0, 120.0);
            const auto stretched = TimeStretch::process (source, rate);

            const auto expectedLength = (int) std::llround ((double) source.getNumSamples() / rate);
            expectEquals (stretched.getNumSamples(), expectedLength);
            expectEquals (stretched.getNumChannels(), source.getNumChannels());

            // Sanity: 120 is faster than 118, so the clip got shorter.
            expect (stretched.getNumSamples() < source.getNumSamples(),
                    "speeding a clip up made it longer");
        }

        beginTest ("the pitch estimator can actually tell a shifted sine apart");
        {
            // Guards the test below: if the estimator were blind, "pitch preserved"
            // would pass for a resampler too and the assertion would prove nothing.
            // 447Hz is where a resample-based 118->120 stretch would land 440.
            expectWithinAbsoluteError (estimateFrequency (makeSine (440.0, 4.0)), 440.0, 1.0);
            expectWithinAbsoluteError (estimateFrequency (makeSine (447.0, 4.0)), 447.0, 1.0);
            expectWithinAbsoluteError (estimateFrequency (makeSine (366.0, 4.0)), 366.0, 1.0);
        }

        beginTest ("AC: the stretch preserves pitch — this is the whole reason it is not a resample");
        {
            const auto source = makeSine (440.0, 4.0);

            for (const auto& pair : { std::pair<double, double> { 118.0, 120.0 },
                                     std::pair<double, double> { 120.0, 100.0 },
                                     std::pair<double, double> { 90.0, 128.0 } })
            {
                const auto rate = TimeStretch::rateFor (pair.first, pair.second);
                const auto stretched = TimeStretch::process (source, rate);

                const auto frequency = estimateFrequency (stretched);
                const auto label = juce::String (pair.first) + " to " + juce::String (pair.second);

                // A resample would land at 440 * rate — 447Hz for the first pair, and
                // 366Hz for the second. Anything near those is a pitch shift.
                expectWithinAbsoluteError (frequency, 440.0, 6.0,
                                           "pitch moved to " + juce::String (frequency)
                                               + "Hz stretching " + label);
            }
        }

        beginTest ("the stretch does not gate or blow up the level");
        {
            const auto source = makeSine (440.0, 4.0);
            const auto stretched = TimeStretch::process (source, TimeStretch::rateFor (118.0, 120.0));

            const auto sourceRms = source.getRMSLevel (0, 0, source.getNumSamples());
            const auto stretchedRms = stretched.getRMSLevel (0, stretched.getNumSamples() / 10,
                                                             stretched.getNumSamples() * 8 / 10);

            expectWithinAbsoluteError (stretchedRms, sourceRms, 0.05f,
                                       "level moved from " + juce::String (sourceRms)
                                           + " to " + juce::String (stretchedRms));
            expect (stretched.getMagnitude (0, stretched.getNumSamples()) <= 1.0f,
                    "the overlap-add clipped");
        }

        beginTest ("slowing a clip down does not leave a silent tail");
        {
            // Slowing down makes the output LONGER than the source, so the analysis
            // reaches the end of the input before the output is full. If the loop stops
            // there, the buffer keeps its zero-filled tail: the file has the right
            // length, so it still lines up to the bar, but it ends in silence.
            const auto source = makeSine (440.0, 4.0);

            for (const auto& pair : { std::pair<double, double> { 120.0, 100.0 },
                                      std::pair<double, double> { 120.0,  70.0 },
                                      std::pair<double, double> { 128.0, 118.0 },
                                      std::pair<double, double> { 120.0,  60.0 },
                                      std::pair<double, double> { 200.0,  60.0 } })
            {
                const auto rate = TimeStretch::rateFor (pair.first, pair.second);
                const auto stretched = TimeStretch::process (source, rate);
                const auto label = juce::String (pair.first) + " to " + juce::String (pair.second);

                expect (stretched.getNumSamples() > source.getNumSamples(),
                        "slowing down did not lengthen the clip");

                // Measure how much of the end is silent, in milliseconds.
                int lastSounding = -1;

                for (int i = stretched.getNumSamples() - 1; i >= 0; --i)
                {
                    if (std::abs (stretched.getSample (0, i)) > 1.0e-4f)
                    {
                        lastSounding = i;
                        break;
                    }
                }

                const auto silentMs = 1000.0 * (double) (stretched.getNumSamples() - 1 - lastSounding)
                                          / sampleRate;

                // One synthesis frame of taper at the end is inherent to overlap-add;
                // a whole analysis frame of dead air is the bug.
                expect (silentMs < 10.0,
                        "stretching " + label + " left " + juce::String (silentMs, 1)
                            + "ms of silence at the end");
            }
        }

        beginTest ("a rate of 1 hands back the samples untouched");
        {
            const auto source = makeSine (440.0, 1.0);
            const auto same = TimeStretch::process (source, 1.0);

            expectEquals (same.getNumSamples(), source.getNumSamples());

            for (int i = 0; i < source.getNumSamples(); ++i)
                if (! juce::approximatelyEqual (same.getReadPointer (0)[i], source.getReadPointer (0)[i]))
                {
                    expect (false, "sample " + juce::String (i) + " was altered at rate 1.0");
                    break;
                }
        }

        beginTest ("silence stays silent, and unusable input does not crash");
        {
            juce::AudioBuffer<float> silence (2, (int) sampleRate);
            silence.clear();

            const auto stretched = TimeStretch::process (silence, TimeStretch::rateFor (118.0, 120.0));
            expect (stretched.getNumSamples() > 0);
            expectEquals (stretched.getMagnitude (0, stretched.getNumSamples()), 0.0f);

            expectEquals (TimeStretch::process ({}, 1.5).getNumSamples(), 0);
            expectEquals (TimeStretch::process (makeSine (440.0, 1.0), 0.0).getNumSamples(), 0);
            expectEquals (TimeStretch::process (makeSine (440.0, 1.0), -1.0).getNumSamples(), 0);
        }

        beginTest ("a clip shorter than one analysis frame is copied rather than mangled");
        {
            juce::AudioBuffer<float> tiny (1, 64);
            tiny.clear();
            tiny.setSample (0, 10, 0.75f);

            const auto stretched = TimeStretch::process (tiny, TimeStretch::rateFor (118.0, 120.0));
            expectEquals (stretched.getNumSamples(), 64);
            expectEquals (stretched.getSample (0, 10), 0.75f);
        }

        //======================================================================
        beginTest ("AC: matchTempo writes a tempo-matched sibling and reuses it");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            const auto clip = dir.directory.getChildFile ("clip.wav");
            expect (writeWav (clip, makeSine (440.0, 2.0)), "could not write the source clip");

            const auto matched = TimeStretch::matchTempo (clip, 118.0, 120.0, formats);

            expect (matched != clip, "no tempo match was produced");
            expect (matched.existsAsFile(), "the tempo-matched file is not on disk");
            expectSameFile (matched, TimeStretch::getMatchedFileFor (clip, 120.0), "unexpected match path");

            std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (matched));
            expect (reader != nullptr, "the tempo-matched file is not readable audio");
            expectEquals ((int) reader->numChannels, 2);
            expectWithinAbsoluteError (reader->sampleRate, sampleRate, 0.5);

            const auto expectedLength = (juce::int64) std::llround (2.0 * sampleRate
                                                                        / TimeStretch::rateFor (118.0, 120.0));
            expect (std::abs (reader->lengthInSamples - expectedLength) <= 1,
                    "length was " + juce::String (reader->lengthInSamples)
                        + ", expected " + juce::String (expectedLength));
            reader.reset();

            // Second call reuses the file rather than stretching again.
            const auto modified = matched.getLastModificationTime();
            const auto again = TimeStretch::matchTempo (clip, 118.0, 120.0, formats);
            expectSameFile (again, matched, "the reused match landed elsewhere");
            expect (again.getLastModificationTime() == modified, "the tempo match was rebuilt");
        }

        beginTest ("matchTempo hands back the original when there is nothing to correct");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            const auto clip = dir.directory.getChildFile ("clip.wav");
            expect (writeWav (clip, makeSine (440.0, 1.0)));

            // Same tempo, unknown clip tempo, unknown host tempo, missing file.
            expectSameFile (TimeStretch::matchTempo (clip, 120.0, 120.0, formats), clip, "stretched a clip already at tempo");
            expectSameFile (TimeStretch::matchTempo (clip, 0.0, 120.0, formats), clip, "stretched with an unknown clip tempo");
            expectSameFile (TimeStretch::matchTempo (clip, 120.0, 0.0, formats), clip, "stretched with an unknown host tempo");

            const auto missing = dir.directory.getChildFile ("nope.wav");
            expectSameFile (TimeStretch::matchTempo (missing, 118.0, 120.0, formats), missing, "a missing clip did not come back unchanged");

            // Unreadable audio is a failure to stretch, not a reason to hand back nothing.
            const auto notAudio = dir.directory.getChildFile ("notaudio.wav");
            notAudio.replaceWithText ("this is not a wav file");
            expectSameFile (TimeStretch::matchTempo (notAudio, 118.0, 120.0, formats), notAudio, "a failed stretch did not fall back to the original");
            expect (! TimeStretch::getMatchedFileFor (notAudio, 120.0).existsAsFile(),
                    "a partial file was left behind by a failed stretch");
        }
    }

private:
    void expectSameFile (const juce::File& actual, const juce::File& expected, const juce::String& what)
    {
        expect (actual == expected,
                what + " — got " + actual.getFullPathName() + ", expected " + expected.getFullPathName());
    }

    struct ScopedTempDir
    {
        ScopedTempDir()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-stretch-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
        }

        ~ScopedTempDir()    { directory.deleteRecursively(); }

        juce::File directory;
    };

    static bool writeWav (const juce::File& file, const juce::AudioBuffer<float>& buffer)
    {
        juce::WavAudioFormat wav;
        std::unique_ptr<juce::OutputStream> stream (file.createOutputStream());

        if (stream == nullptr)
            return false;

        auto writer = wav.createWriterFor (stream, juce::AudioFormatWriterOptions{}
                                                       .withSampleRate (sampleRate)
                                                       .withNumChannels (buffer.getNumChannels())
                                                       .withBitsPerSample (16));

        if (writer == nullptr)
            return false;

        return writer->writeFromAudioSampleBuffer (buffer, 0, buffer.getNumSamples());
    }
};

static TimeStretchTests timeStretchTests;

} // namespace acemusic
