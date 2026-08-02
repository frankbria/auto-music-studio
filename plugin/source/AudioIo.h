#pragma once

#include <juce_audio_formats/juce_audio_formats.h>

namespace acemusic
{

/**
    The one place a buffer becomes a file on disk.

    Extracted at its third caller (TimeStretch, MidiCapture, SidechainCapture) rather
    than up front. All three want the same thing and the same care: write to a temporary
    and move it into place, so nothing can ever read a half-written WAV and treat it as
    a finished one.
*/
namespace AudioIo
{
    /** Writes `buffer` to `destination` as a 16-bit WAV, creating the parent directory.

        The write goes to a `.partial` sibling first and is moved into place only once
        complete; on any failure the partial is removed and `destination` is left as it
        was. Touches the disk, so: never the audio thread.

        @returns false if the buffer is empty, or the write or the move failed. */
    bool writeWav (const juce::File& destination,
                   const juce::AudioBuffer<float>& buffer,
                   double sampleRate,
                   int bitsPerSample = 16);
}

} // namespace acemusic
