#pragma once

#include <juce_audio_formats/juce_audio_formats.h>

namespace acemusic
{

/**
    Pitch-preserving time-stretch, for matching a generated clip to the host tempo.

    **Why not just resample.** `juce::LagrangeInterpolator` would be a third of this
    code, but resampling changes pitch with speed: the story's own example, 118 BPM to
    120 BPM, is a 1.7% rate change and therefore a 29-cent detune. A feature whose
    entire purpose is "generated music matches my project" must not hand back audio
    that arrives out of tune with the project, so this is WSOLA (waveform-similarity
    overlap-add) instead — the standard algorithm for small tempo edits, no new
    dependency, and pitch-transparent at the ratios this feature actually sees.

    Rate semantics mirror `calculate_speed_multiplier` / `time_stretch_audio` in
    `src/acemusic/audio.py` so the plugin and the Python side cannot disagree about
    direction: `rate = target / original`, rate > 1 plays faster, and the output is
    `length / rate` samples long.
*/
namespace TimeStretch
{
    /** The rate that turns a `fromBpm` clip into a `toBpm` one, or 0 when either
        tempo is not a positive number. */
    double rateFor (double fromBpm, double toBpm) noexcept;

    /** Whether `rate` is far enough from 1.0 to be worth the work.

        The threshold is a quarter of a percent — below that the correction is under
        one sample per 400 and well inside the rounding of any BPM the panel can
        express, so stretching would only add artefacts.

        There is deliberately no upper or lower bound: the trailing-silence that a
        large slowdown used to leave was a bug in the analysis loop, not a limit of the
        method, and once fixed a 3.3x stretch measures the same clean tail as a 1.02x
        one. See the "silent tail" test, which covers both. */
    bool isWorthStretching (double rate) noexcept;

    /** WSOLA-stretches `source`, returning a buffer of `source.getNumSamples() / rate`
        samples. Returns a plain copy when the rate is not worth stretching, and an
        empty buffer when the input is unusable. */
    juce::AudioBuffer<float> process (const juce::AudioBuffer<float>& source, double rate);

    /** Reads `source`, stretches it, and writes `destination` as a WAV at the source's
        sample rate and bit depth. @returns false if the read or the write failed;
        `destination` is not left behind as a partial file in that case. */
    bool processFile (const juce::File& source,
                      const juce::File& destination,
                      double rate,
                      juce::AudioFormatManager& formats);

    /** Where a `clip` tempo-matched to `targetBpm` is cached: a `tempo-match/` child of
        the clip's own run directory.

        A child directory rather than a sibling file, because ClipCache::readEntry
        lists `*.wav` per run non-recursively — as siblings these were counted as extra
        clips of that generation. The cache's size accounting recurses and its delete is
        recursive, so they are still measured and still removed with the run. */
    juce::File getMatchedFileFor (const juce::File& clip, double targetBpm);

    /** Produces (or reuses) a copy of `clip` at `targetBpm`, given that it was
        generated at `clipBpm`.

        @returns the tempo-matched file, or `clip` itself when either tempo is unknown,
                 the difference is not worth stretching, or the stretch failed —
                 handing back the original is always better than handing back nothing.
                 Reads and writes files, so: never the audio thread. */
    juce::File matchTempo (const juce::File& clip,
                           double clipBpm,
                           double targetBpm,
                           juce::AudioFormatManager& formats);
}

} // namespace acemusic
