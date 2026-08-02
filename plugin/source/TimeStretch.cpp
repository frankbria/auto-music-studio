#include "TimeStretch.h"

#include <cmath>
#include <vector>

namespace acemusic
{
namespace TimeStretch
{

namespace
{
    /** 2048 at 44.1kHz is ~46ms: long enough to hold a full period of anything with a
        recognisable pitch, short enough that transients are not smeared across it. */
    constexpr int frameSize = 2048;

    /** 50% overlap. A Hann window at 50% overlap sums to a constant, so the
        overlap-add needs no normalisation pass afterwards. */
    constexpr int synthesisHop = frameSize / 2;

    /** How far the similarity search may slide a frame from its ideal position.
        128 samples covers a full period down to ~345Hz at 44.1kHz, which is where
        the audible periodicity of most material lives. */
    constexpr int searchRadius = 128;

    /** Only the head of the frame is correlated, not all 2048 samples.
        ponytail: 256x257 comparisons per frame keeps a 60s stereo clip well under a
        tenth of a second. Widen this (or decimate and do a coarse-to-fine search) if
        a future story ever stretches by more than a few percent, where the alignment
        matters more than it does here.  */
    constexpr int correlationLength = 256;

    std::vector<float> makeHannWindow()
    {
        std::vector<float> window ((size_t) frameSize);

        for (int i = 0; i < frameSize; ++i)
            window[(size_t) i] = (float) (0.5 - 0.5 * std::cos (juce::MathConstants<double>::twoPi
                                                                   * (double) i / (double) (frameSize - 1)));

        return window;
    }

    /** Finds where in `reference` the material starting at `idealStart` best continues
        the frame that ended at `templateStart`. This is the "waveform similarity" half
        of WSOLA: without it, overlap-add at a shifted hop cancels partials against
        themselves and the result phases badly.

        Correlation runs on one channel and the winning offset is applied to all of
        them — searching per channel would slide the channels apart and collapse the
        stereo image. */
    int findBestStart (const float* reference,
                       int numSamples,
                       int idealStart,
                       int templateStart)
    {
        // A candidate only needs room for the *correlation*, not for a whole frame.
        // Slowing a clip down means the output is longer than the source, so the last
        // frames legitimately start near the end and read a partial frame; requiring a
        // full frame here would pin them in place and leave the output's tail unwritten.
        const int lastCandidate = numSamples - correlationLength;

        if (lastCandidate <= 0)
            return 0;

        // Nothing to correlate against if the template runs off the end.
        if (templateStart < 0 || templateStart + correlationLength > numSamples)
            return juce::jlimit (0, lastCandidate, idealStart);

        int best = juce::jlimit (0, lastCandidate, idealStart);
        double bestScore = -1.0e30;

        for (int offset = -searchRadius; offset <= searchRadius; ++offset)
        {
            const int candidate = idealStart + offset;

            if (candidate < 0 || candidate > lastCandidate)
                continue;

            double dot = 0.0;
            double energy = 0.0;

            for (int i = 0; i < correlationLength; ++i)
            {
                const double sample = (double) reference[candidate + i];
                dot    += (double) reference[templateStart + i] * sample;
                energy += sample * sample;
            }

            // Normalised by the candidate's energy, so a loud passage cannot win the
            // search just for being loud.
            const double score = dot / std::sqrt (energy + 1.0e-9);

            if (score > bestScore)
            {
                bestScore = score;
                best = candidate;
            }
        }

        return best;
    }
}

//==============================================================================
double rateFor (double fromBpm, double toBpm) noexcept
{
    if (fromBpm <= 0.0 || toBpm <= 0.0)
        return 0.0;

    return toBpm / fromBpm;
}

bool isWorthStretching (double rate) noexcept
{
    return rate > 0.0 && std::abs (rate - 1.0) > 0.0025;
}

//==============================================================================
juce::AudioBuffer<float> process (const juce::AudioBuffer<float>& source, double rate)
{
    const int numChannels = source.getNumChannels();
    const int numSamples  = source.getNumSamples();

    if (numChannels <= 0 || numSamples <= 0 || rate <= 0.0)
        return {};

    juce::AudioBuffer<float> copy;

    // Anything too short to hold a single analysis frame has no periodicity to
    // preserve; copying it is both cheaper and less damaging than windowing it.
    if (! isWorthStretching (rate) || numSamples <= frameSize)
    {
        copy.makeCopyOf (source);
        return copy;
    }

    const int outputLength = (int) std::llround ((double) numSamples / rate);

    if (outputLength <= 0)
        return {};

    juce::AudioBuffer<float> output (numChannels, outputLength);
    output.clear();

    const auto window = makeHannWindow();

    // The first frame is emitted without the window's rising half. Otherwise every
    // stretched clip would fade in over ~23ms, which is plainly audible when the clip
    // starts on a downbeat. The fade at the *end* is left alone: it lands in the
    // clip's own decay.
    auto leadingWindow = window;
    std::fill (leadingWindow.begin(), leadingWindow.begin() + synthesisHop, 1.0f);

    const float* const reference = source.getReadPointer (0);

    int previousStart = 0;

    for (int frame = 0; frame * synthesisHop < outputLength; ++frame)
    {
        const int outPos = frame * synthesisHop;

        // The ideal analysis position is derived from the frame index in floating
        // point rather than accumulated hop by hop, so rounding cannot drift the
        // output length away from numSamples/rate over a long clip.
        const int idealStart = (int) std::llround ((double) frame * (double) synthesisHop * rate);

        const int start = frame == 0
                            ? 0
                            : findBestStart (reference, numSamples, idealStart,
                                             previousStart + synthesisHop);

        const float* const shape = (frame == 0 ? leadingWindow : window).data();

        // Deliberately allowed to be shorter than a frame near the end of the input:
        // that turns the last few milliseconds into a taper rather than a hard gap.
        const int length = juce::jmin (frameSize,
                                       numSamples - start,
                                       outputLength - outPos);

        for (int channel = 0; channel < numChannels; ++channel)
        {
            const float* in = source.getReadPointer (channel) + start;
            float* out = output.getWritePointer (channel) + outPos;

            for (int i = 0; i < length; ++i)
                out[i] += in[i] * shape[i];
        }

        previousStart = start;
    }

    return output;
}

//==============================================================================
bool processFile (const juce::File& source,
                  const juce::File& destination,
                  double rate,
                  juce::AudioFormatManager& formats)
{
    std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (source));

    if (reader == nullptr || reader->numChannels == 0 || reader->lengthInSamples <= 0)
        return false;

    // Guard against a caller pointing this at something enormous: the whole clip is
    // held in memory twice while it is stretched. Generated clips are minutes at most.
    constexpr juce::int64 maxSamples = 60 * 60 * 192000;

    if (reader->lengthInSamples > maxSamples)
        return false;

    juce::AudioBuffer<float> input ((int) reader->numChannels, (int) reader->lengthInSamples);

    if (! reader->read (&input, 0, (int) reader->lengthInSamples, 0, true, true))
        return false;

    const auto stretched = process (input, rate);

    if (stretched.getNumSamples() <= 0)
        return false;

    const auto sampleRate = reader->sampleRate;
    const auto bitDepth = juce::jmax (16, (int) reader->bitsPerSample);
    const auto numChannels = (unsigned int) stretched.getNumChannels();

    // Written to a temporary first: a reader that finds a half-written file next to a
    // clip would treat it as a finished tempo match and hand the host a truncated drop.
    destination.getParentDirectory().createDirectory();

    const auto partial = destination.getSiblingFile (destination.getFileName() + ".partial");
    partial.deleteFile();

    {
        juce::WavAudioFormat wav;
        std::unique_ptr<juce::OutputStream> stream (partial.createOutputStream());

        if (stream == nullptr)
            return false;

        auto writer = wav.createWriterFor (stream, juce::AudioFormatWriterOptions{}
                                                       .withSampleRate (sampleRate)
                                                       .withNumChannels ((int) numChannels)
                                                       .withBitsPerSample (bitDepth));

        if (writer == nullptr)
            return false;

        if (! writer->writeFromAudioSampleBuffer (stretched, 0, stretched.getNumSamples()))
        {
            writer.reset();
            partial.deleteFile();
            return false;
        }
    }

    destination.deleteFile();

    if (! partial.moveFileTo (destination))
    {
        partial.deleteFile();
        return false;
    }

    return true;
}

//==============================================================================
juce::File getMatchedFileFor (const juce::File& clip, double targetBpm)
{
    // In a child directory rather than beside the clip. ClipCache::readEntry lists
    // `*.wav` in a run directory non-recursively, so a sibling would be picked up as
    // an *extra clip of that generation* — a two-clip run would list four. A child
    // directory is invisible to that scan, but is still counted by the cache's size
    // (which recurses) and removed with the run (which deletes recursively).
    return clip.getParentDirectory()
               .getChildFile ("tempo-match")
               .getChildFile (clip.getFileNameWithoutExtension()
                                  + "-" + juce::String (juce::roundToInt (targetBpm)) + "bpm.wav");
}

juce::File matchTempo (const juce::File& clip,
                       double clipBpm,
                       double targetBpm,
                       juce::AudioFormatManager& formats)
{
    const auto rate = rateFor (clipBpm, targetBpm);

    if (! isWorthStretching (rate) || ! clip.existsAsFile())
        return clip;

    const auto matched = getMatchedFileFor (clip, targetBpm);

    if (matched.existsAsFile() && matched.getSize() > 0)
        return matched;

    if (! processFile (clip, matched, rate, formats))
        return clip;

    return matched;
}

} // namespace TimeStretch
} // namespace acemusic
