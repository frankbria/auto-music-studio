#include "PluginProcessor.h"

#include <atomic>
#include <thread>

namespace acemusic
{

class ClipPlayerTests final : public juce::UnitTest
{
public:
    ClipPlayerTests()
        : juce::UnitTest ("ClipPlayer", "acemusic")
    {
    }

    /** A real WAV on disk — the player opens files, so a buffer would not exercise it. */
    struct ScopedWav
    {
        explicit ScopedWav (double seconds = 1.0, int channels = 1, double frequency = 440.0)
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-clip-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
            file = directory.getChildFile ("clip.wav");

            const auto sampleRate = 44100.0;
            const auto numSamples = (int) (seconds * sampleRate);

            juce::AudioBuffer<float> buffer (channels, numSamples);

            for (int channel = 0; channel < channels; ++channel)
                for (int sample = 0; sample < numSamples; ++sample)
                    buffer.setSample (channel, sample,
                                      0.5f * std::sin (2.0f * juce::MathConstants<float>::pi
                                                       * (float) frequency * (float) sample / (float) sampleRate));

            juce::WavAudioFormat format;
            std::unique_ptr<juce::OutputStream> stream (file.createOutputStream());

            if (stream != nullptr)
            {
                const auto options = juce::AudioFormatWriterOptions{}
                                         .withSampleRate (sampleRate)
                                         .withNumChannels (channels)
                                         .withBitsPerSample (16);

                if (auto writer = format.createWriterFor (stream, options))
                    writer->writeFromAudioSampleBuffer (buffer, 0, numSamples);
            }
        }

        ~ScopedWav()  { directory.deleteRecursively(); }

        juce::File directory, file;
    };

    static std::unique_ptr<PluginProcessor> makeOfflineProcessor()
    {
        return std::make_unique<PluginProcessor> (nullptr, false);
    }

    /** Runs `blocks` of processBlock and reports the peak level produced. */
    static float renderPeak (PluginProcessor& processor, int blocks, int blockSize = 512)
    {
        juce::AudioBuffer<float> buffer (2, blockSize);
        juce::MidiBuffer midi;
        float peak = 0.0f;

        for (int i = 0; i < blocks; ++i)
        {
            buffer.clear();
            processor.processBlock (buffer, midi);
            peak = juce::jmax (peak, buffer.getMagnitude (0, blockSize));
        }

        return peak;
    }

    void runTest() override
    {
        beginTest ("refuses a file it cannot read");
        {
            ClipPlayer player;
            player.prepare (44100.0, 512);

            expect (! player.load (juce::File()), "accepted an empty path");
            expect (! player.load (juce::File::getSpecialLocation (juce::File::tempDirectory)
                                       .getChildFile ("definitely-not-here.wav")),
                    "accepted a missing file");

            const auto notAudio = juce::File::getSpecialLocation (juce::File::tempDirectory)
                                      .getChildFile ("acemusic-not-audio.txt");
            notAudio.replaceWithText ("this is not a wav");
            expect (! player.load (notAudio), "accepted a text file as audio");
            notAudio.deleteFile();

            expect (! player.isPlaying());
        }

        beginTest ("loads a clip and reports its length");
        {
            ScopedWav wav { 1.5 };

            ClipPlayer player;
            player.prepare (44100.0, 512);

            expect (player.load (wav.file), "could not load a valid wav");
            expectEquals (player.getCurrentFile().getFullPathName(), wav.file.getFullPathName());
            expectWithinAbsoluteError (player.getLength(), 1.5, 0.05);
            expect (! player.isPlaying(), "started playing without being asked");
        }

        beginTest ("AC: a loaded clip is audible in the plugin's output");
        {
            ScopedWav wav;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 512);

            // Silent before anything is playing — the plugin is a passthrough and the
            // test feeds it silence.
            expectEquals (renderPeak (processor, 4), 0.0f, "produced audio while idle");

            expect (processor.getClipPlayer().load (wav.file));
            processor.getClipPlayer().play();
            expect (processor.getClipPlayer().isPlaying());

            const auto peak = renderPeak (processor, 8);
            expect (peak > 0.1f, "the clip was not mixed into the output, peak was "
                                     + juce::String (peak));
        }

        beginTest ("stopping silences the output again");
        {
            ScopedWav wav;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 512);

            expect (processor.getClipPlayer().load (wav.file));
            processor.getClipPlayer().play();
            expect (renderPeak (processor, 4) > 0.1f, "never produced audio");

            processor.getClipPlayer().stop();
            expect (! processor.getClipPlayer().isPlaying());
            expectEquals (renderPeak (processor, 4), 0.0f, "still producing audio after stop");
        }

        beginTest ("a mono clip reaches both output channels");
        {
            ScopedWav wav { 1.0, 1 };

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 512);

            expect (processor.getClipPlayer().load (wav.file));
            processor.getClipPlayer().play();

            juce::AudioBuffer<float> buffer (2, 512);
            juce::MidiBuffer midi;
            float leftPeak = 0.0f, rightPeak = 0.0f;

            for (int i = 0; i < 8; ++i)
            {
                buffer.clear();
                processor.processBlock (buffer, midi);
                leftPeak  = juce::jmax (leftPeak,  buffer.getMagnitude (0, 0, 512));
                rightPeak = juce::jmax (rightPeak, buffer.getMagnitude (1, 0, 512));
            }

            expect (leftPeak > 0.1f, "nothing on the left");
            expect (rightPeak > 0.1f, "a mono clip was left-only, right peak was "
                                          + juce::String (rightPeak));
        }

        beginTest ("toggle starts, stops, and switches clips");
        {
            ScopedWav first, second;

            ClipPlayer player;
            player.prepare (44100.0, 512);

            expect (player.toggle (first.file), "could not start the first clip");
            expect (player.isPlaying());
            expectEquals (player.getCurrentFile().getFullPathName(), first.file.getFullPathName());

            // Toggling the same clip stops it.
            expect (player.toggle (first.file));
            expect (! player.isPlaying(), "toggling the playing clip did not stop it");

            // Toggling a different clip switches and plays.
            expect (player.toggle (second.file));
            expect (player.isPlaying());
            expectEquals (player.getCurrentFile().getFullPathName(), second.file.getFullPathName());
        }

        beginTest ("processBlock stays safe while clips are swapped underneath it");
        {
            // The real hazard: the message thread loading a new clip while the audio
            // thread is mid-block. processBlock try-locks and skips rather than
            // blocking, so this must neither crash nor deadlock.
            ScopedWav first, second;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 512);

            expect (processor.getClipPlayer().load (first.file));
            processor.getClipPlayer().play();

            std::atomic<bool> stop { false };
            std::atomic<int> loads { 0 };

            std::thread loader ([&]
            {
                while (! stop.load())
                {
                    processor.getClipPlayer().load ((loads % 2 == 0) ? first.file : second.file);
                    processor.getClipPlayer().play();
                    ++loads;
                }
            });

            juce::AudioBuffer<float> buffer (2, 512);
            juce::MidiBuffer midi;

            for (int i = 0; i < 400; ++i)
            {
                buffer.clear();
                processor.processBlock (buffer, midi);
            }

            stop = true;
            loader.join();

            expect (loads.load() > 0, "the loader never ran");
            expect (true, "survived concurrent loads during playback");
        }

        beginTest ("a host block larger than promised does not overrun the scratch buffer");
        {
            // prepareToPlay sizes everything the audio thread uses. A host that then
            // hands over a bigger block must not make us allocate or read past the end.
            ScopedWav wav;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 256);

            expect (processor.getClipPlayer().load (wav.file));
            processor.getClipPlayer().play();

            juce::AudioBuffer<float> oversized (2, 2048);
            juce::MidiBuffer midi;
            oversized.clear();
            processor.processBlock (oversized, midi);

            // The first 256 samples get audio; the rest stay as the host left them.
            expect (oversized.getMagnitude (0, 0, 256) > 0.0f, "no audio in the prepared range");
            expect (true, "survived an oversized block");
        }

        beginTest ("playing survives prepareToPlay being called again, in both directions");
        {
            ScopedWav wav;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            processor.prepareToPlay (44100.0, 512);

            expect (processor.getClipPlayer().load (wav.file));
            processor.getClipPlayer().play();

            // Hosts re-prepare on sample-rate or block-size changes. Shrinking first.
            processor.prepareToPlay (48000.0, 256);
            expect (renderPeak (processor, 4, 256) > 0.1f, "went silent after shrinking the block");

            // And then GROWING, which is the direction that matters: the scratch
            // buffer has to actually grow, or every block gets clamped to the old
            // smaller size and the preview plays fast with gaps.
            processor.prepareToPlay (44100.0, 1024);

            juce::AudioBuffer<float> buffer (2, 1024);
            juce::MidiBuffer midi;
            float tailPeak = 0.0f;

            for (int i = 0; i < 4; ++i)
            {
                buffer.clear();
                processor.processBlock (buffer, midi);
                // The second half is what a stale, too-small scratch buffer would
                // leave silent.
                tailPeak = juce::jmax (tailPeak, buffer.getMagnitude (0, 512, 512));
            }

            expect (tailPeak > 0.1f,
                    "the back half of a grown block was silent — the scratch buffer did not grow");
        }
    }
};

static ClipPlayerTests clipPlayerTests;

} // namespace acemusic
