#include "LegoStack.h"
#include "AudioIo.h"

namespace acemusic
{

namespace
{
    /** Reads a whole clip into memory. Returns an empty buffer if it is unreadable, so a
        missing layer degrades the mix rather than failing the whole build. */
    juce::AudioBuffer<float> readClip (const juce::File& file,
                                       juce::AudioFormatManager& formats,
                                       double& sampleRateOut)
    {
        std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (file));

        if (reader == nullptr || reader->numChannels == 0 || reader->lengthInSamples <= 0)
            return {};

        // Same bound as TimeStretch: layers are minutes at most, and the mix holds them
        // all at once.
        constexpr juce::int64 maxSamples = 60 * 60 * 192000;

        if (reader->lengthInSamples > maxSamples)
            return {};

        juce::AudioBuffer<float> buffer ((int) reader->numChannels, (int) reader->lengthInSamples);

        if (! reader->read (&buffer, 0, (int) reader->lengthInSamples, 0, true, true))
            return {};

        sampleRateOut = reader->sampleRate;
        return buffer;
    }
}

//==============================================================================
juce::StringArray LegoStack::trackNames()
{
    // ACE-Step's TRACK_NAMES, in its own order (acestep/constants.py).
    return { "drums", "bass", "guitar", "keyboard", "synth", "strings",
             "brass", "woodwinds", "percussion", "fx", "vocals", "backing_vocals" };
}

juce::String LegoStack::instructionFor (const juce::String& track)
{
    if (track.isEmpty())
        return {};

    // Matches ACE-Step's TASK_INSTRUCTIONS["lego"]:
    //   "Generate the {TRACK_NAME} track based on the audio context:"
    // with TRACK_NAME upper-cased, as its CLI does.
    return "Generate the " + track.toUpperCase() + " track based on the audio context:";
}

//==============================================================================
void LegoStack::addLayer (const juce::String& track, const juce::String& prompt, const juce::File& clip)
{
    layers.add ({ track, prompt, clip, true });
}

bool LegoStack::replaceLayer (int index, const juce::File& clip)
{
    if (! juce::isPositiveAndBelow (index, layers.size()))
        return false;

    // Only the clip changes: the track and prompt describe what this layer *is*, and a
    // regeneration is the same layer done again.
    auto layer = layers[index];
    layer.clip = clip;
    layers.set (index, layer);
    return true;
}

bool LegoStack::removeLayer (int index)
{
    if (! juce::isPositiveAndBelow (index, layers.size()))
        return false;

    layers.remove (index);
    return true;
}

bool LegoStack::setLayerEnabled (int index, bool enabled)
{
    if (! juce::isPositiveAndBelow (index, layers.size()))
        return false;

    auto layer = layers[index];
    layer.enabled = enabled;
    layers.set (index, layer);
    return true;
}

void LegoStack::clear()
{
    layers.clear();
}

//==============================================================================
bool LegoStack::hasContext (int excludeIndex) const
{
    for (int i = 0; i < layers.size(); ++i)
        if (i != excludeIndex && layers[i].enabled && layers[i].clip.existsAsFile())
            return true;

    return false;
}

double LegoStack::getContextSampleRate (juce::AudioFormatManager& formats) const
{
    for (const auto& layer : layers)
    {
        if (! layer.enabled)
            continue;

        std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (layer.clip));

        if (reader != nullptr && reader->sampleRate > 0.0)
            return reader->sampleRate;
    }

    return 44100.0;
}

juce::AudioBuffer<float> LegoStack::mixContext (juce::AudioFormatManager& formats, int excludeIndex) const
{
    juce::Array<juce::AudioBuffer<float>> loaded;
    int longest = 0;
    int channels = 1;

    for (int i = 0; i < layers.size(); ++i)
    {
        if (i == excludeIndex || ! layers[i].enabled)
            continue;

        double rate = 0.0;
        auto buffer = readClip (layers[i].clip, formats, rate);

        if (buffer.getNumSamples() <= 0)
            continue;

        longest = juce::jmax (longest, buffer.getNumSamples());
        channels = juce::jmax (channels, buffer.getNumChannels());
        loaded.add (std::move (buffer));
    }

    if (loaded.isEmpty())
        return {};

    juce::AudioBuffer<float> mix (channels, longest);
    mix.clear();

    for (const auto& buffer : loaded)
    {
        for (int channel = 0; channel < channels; ++channel)
        {
            // A mono layer is spread across the mix rather than left in one ear.
            const auto sourceChannel = juce::jmin (channel, buffer.getNumChannels() - 1);
            mix.addFrom (channel, 0, buffer, sourceChannel, 0, buffer.getNumSamples());
        }
    }

    // Layers are summed, so a full arrangement will run past full scale. Scaling the
    // whole mix keeps the balance the musician built; clipping would not.
    const auto peak = mix.getMagnitude (0, longest);

    if (peak > 1.0f)
        mix.applyGain (1.0f / peak);

    return mix;
}

bool LegoStack::writeContext (const juce::File& destination,
                              juce::AudioFormatManager& formats,
                              int excludeIndex) const
{
    const auto mix = mixContext (formats, excludeIndex);

    if (mix.getNumSamples() <= 0)
        return false;

    return AudioIo::writeWav (destination, mix, getContextSampleRate (formats));
}

} // namespace acemusic
