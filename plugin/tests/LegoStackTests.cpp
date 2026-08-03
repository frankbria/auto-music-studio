#include "LegoStack.h"

#include <cmath>

namespace acemusic
{

class LegoStackTests final : public juce::UnitTest
{
public:
    LegoStackTests()
        : juce::UnitTest ("LegoStack", "acemusic")
    {
    }

    static constexpr double sampleRate = 44100.0;

    struct ScopedTempDir
    {
        ScopedTempDir()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-lego-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();
        }

        ~ScopedTempDir()    { directory.deleteRecursively(); }

        juce::File directory;
    };

    /** A one-second tone at `frequency`, so each layer is identifiable in a mix. */
    static juce::File writeTone (const juce::File& file, double frequency, int channels = 1)
    {
        const int numSamples = (int) sampleRate;
        juce::AudioBuffer<float> buffer (channels, numSamples);

        for (int channel = 0; channel < channels; ++channel)
            for (int i = 0; i < numSamples; ++i)
                buffer.setSample (channel, i,
                                  0.3f * (float) std::sin (juce::MathConstants<double>::twoPi
                                                           * frequency * (double) i / sampleRate));

        juce::WavAudioFormat wav;
        std::unique_ptr<juce::OutputStream> stream (file.createOutputStream());

        if (stream != nullptr)
        {
            auto writer = wav.createWriterFor (stream, juce::AudioFormatWriterOptions{}
                                                           .withSampleRate (sampleRate)
                                                           .withNumChannels (channels)
                                                           .withBitsPerSample (16));
            if (writer != nullptr)
                writer->writeFromAudioSampleBuffer (buffer, 0, numSamples);
        }

        return file;
    }

    /** Energy at `frequency`, so a mix can be asked which layers are in it. */
    static double energyAt (const juce::AudioBuffer<float>& buffer, double frequency)
    {
        const auto* data = buffer.getReadPointer (0);
        const auto n = buffer.getNumSamples();
        double re = 0.0, im = 0.0;

        for (int i = 0; i < n; ++i)
        {
            const auto phase = juce::MathConstants<double>::twoPi * frequency * (double) i / sampleRate;
            re += data[i] * std::cos (phase);
            im += data[i] * std::sin (phase);
        }

        return std::sqrt (re * re + im * im) / (double) n;
    }

    void runTest() override
    {
        beginTest ("the track list is ACE-Step's, not one of our own");
        {
            const auto tracks = LegoStack::trackNames();

            // Every name here has to exist in ACE-Step's TRACK_NAMES, or the instruction
            // describes a track the model was never trained on.
            for (const auto* expected : { "drums", "bass", "guitar", "keyboard", "synth",
                                          "strings", "brass", "woodwinds", "percussion",
                                          "fx", "vocals", "backing_vocals" })
            {
                expect (tracks.contains (expected), juce::String (expected) + " is missing");
            }

            expectEquals (tracks.size(), 12);
        }

        beginTest ("the instruction matches the template the server steers off");
        {
            expectEquals (LegoStack::instructionFor ("bass"),
                          juce::String ("Generate the BASS track based on the audio context:"));
            expectEquals (LegoStack::instructionFor ("backing_vocals"),
                          juce::String ("Generate the BACKING_VOCALS track based on the audio context:"));
            expect (LegoStack::instructionFor ("").isEmpty(), "an empty track produced an instruction");
        }

        beginTest ("an empty stack has no context to build on");
        {
            LegoStack stack;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            expect (! stack.hasContext(), "an empty stack claimed to have context");
            expectEquals (stack.mixContext (formats).getNumSamples(), 0);
            expectEquals (stack.getNumLayers(), 0);
        }

        beginTest ("AC: the context mix contains every layer built so far");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "a tight beat", writeTone (dir.directory.getChildFile ("l1.wav"), 220.0));
            stack.addLayer ("bass",  "a funky line", writeTone (dir.directory.getChildFile ("l2.wav"), 330.0));

            expect (stack.hasContext());
            expectEquals (stack.getNumLayers(), 2);

            const auto mix = stack.mixContext (formats);
            expect (mix.getNumSamples() > 0, "nothing was mixed");

            // Both layers are audible in the mix, and nothing else is.
            expect (energyAt (mix, 220.0) > 0.05, "the drums layer is missing from the context");
            expect (energyAt (mix, 330.0) > 0.05, "the bass layer is missing from the context");
            expect (energyAt (mix, 550.0) < 0.01, "the mix contains a layer that was never added");
        }

        beginTest ("a muted layer stays in the list but leaves the context");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("l1.wav"), 220.0));
            stack.addLayer ("bass",  "line", writeTone (dir.directory.getChildFile ("l2.wav"), 330.0));

            expect (stack.setLayerEnabled (1, false));
            expectEquals (stack.getNumLayers(), 2, "muting removed the layer");

            const auto mix = stack.mixContext (formats);
            expect (energyAt (mix, 220.0) > 0.05, "the enabled layer left the mix");
            expect (energyAt (mix, 330.0) < 0.01, "a muted layer was still in the context");
        }

        beginTest ("AC: regenerating one layer leaves the others untouched");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            const auto drums = writeTone (dir.directory.getChildFile ("drums.wav"), 220.0);
            const auto bass  = writeTone (dir.directory.getChildFile ("bass.wav"), 330.0);
            stack.addLayer ("drums", "beat", drums);
            stack.addLayer ("bass",  "line", bass);

            const auto drumsBefore = drums.getSize();
            const auto newBass = writeTone (dir.directory.getChildFile ("bass2.wav"), 440.0);

            expect (stack.replaceLayer (1, newBass));

            expectEquals (stack.getNumLayers(), 2, "regenerating changed the layer count");
            expectEquals (stack.getLayers()[0].clip.getFullPathName(), drums.getFullPathName(),
                          "the drums layer was disturbed by regenerating the bass");
            expectEquals (drums.getSize(), drumsBefore, "the drums file itself was rewritten");

            // The track and prompt describe what the layer *is*, so a regeneration keeps them.
            expectEquals (stack.getLayers()[1].track, juce::String ("bass"));
            expectEquals (stack.getLayers()[1].prompt, juce::String ("line"));

            const auto mix = stack.mixContext (formats);
            expect (energyAt (mix, 440.0) > 0.05, "the regenerated layer is not in the mix");
            expect (energyAt (mix, 330.0) < 0.01, "the replaced layer is still in the mix");
        }

        beginTest ("a layer being regenerated is excluded from its own context");
        {
            // The whole point: a replacement bass should fit the drums it sits under,
            // not the bass it is replacing.
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("l1.wav"), 220.0));
            stack.addLayer ("bass",  "line", writeTone (dir.directory.getChildFile ("l2.wav"), 330.0));

            const auto context = stack.mixContext (formats, 1);

            expect (energyAt (context, 220.0) > 0.05, "the drums left the regeneration context");
            expect (energyAt (context, 330.0) < 0.01,
                    "the layer being regenerated was fed back in as its own context");

            // With only one layer, regenerating it leaves nothing to build on — which
            // makes it a first-layer generation again.
            LegoStack single;
            single.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("l3.wav"), 220.0));
            expect (! single.hasContext (0), "a lone layer claimed itself as context");
            expectEquals (single.mixContext (formats, 0).getNumSamples(), 0);
        }

        beginTest ("layers of different lengths and channel counts mix without clipping");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("mono.wav"), 220.0, 1));
            stack.addLayer ("bass", "line", writeTone (dir.directory.getChildFile ("stereo.wav"), 330.0, 2));

            const auto mix = stack.mixContext (formats);
            expectEquals (mix.getNumChannels(), 2, "the mix collapsed to the narrowest layer");
            expect (mix.getMagnitude (0, mix.getNumSamples()) <= 1.0f, "the layer mix clipped");

            // The mono layer reaches both channels rather than sitting in one ear.
            expect (energyAt (mix, 220.0) > 0.05);
        }

        beginTest ("writing the context produces a readable WAV, and nothing when empty");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("l1.wav"), 220.0));

            const auto out = dir.directory.getChildFile ("ctx").getChildFile ("context.wav");
            expect (stack.writeContext (out, formats), "the context write failed");

            std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (out));
            expect (reader != nullptr, "the context is not readable audio");
            expectWithinAbsoluteError (reader->sampleRate, sampleRate, 0.5);

            LegoStack empty;
            const auto none = dir.directory.getChildFile ("none.wav");
            expect (! empty.writeContext (none, formats), "an empty stack wrote a context");
            expect (! none.existsAsFile());
        }

        beginTest ("a layer whose file has gone missing degrades the mix rather than failing it");
        {
            ScopedTempDir dir;
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();

            LegoStack stack;
            stack.addLayer ("drums", "beat", writeTone (dir.directory.getChildFile ("l1.wav"), 220.0));
            stack.addLayer ("bass", "line", dir.directory.getChildFile ("never-written.wav"));

            expect (stack.hasContext(), "one missing layer took the whole context down");

            const auto mix = stack.mixContext (formats);
            expect (mix.getNumSamples() > 0, "a missing layer emptied the mix");
            expect (energyAt (mix, 220.0) > 0.05, "the surviving layer was lost too");
        }

        beginTest ("out-of-range edits are refused rather than corrupting the stack");
        {
            LegoStack stack;
            expect (! stack.replaceLayer (0, {}));
            expect (! stack.removeLayer (0));
            expect (! stack.setLayerEnabled (0, false));

            stack.addLayer ("drums", "beat", {});
            expect (! stack.replaceLayer (1, {}));
            expect (! stack.replaceLayer (-1, {}));
            expectEquals (stack.getNumLayers(), 1);
        }
    }
};

static LegoStackTests legoStackTests;

} // namespace acemusic
