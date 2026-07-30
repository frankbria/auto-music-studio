#pragma once

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_utils/juce_audio_utils.h>

namespace acemusic
{

/**
    Previews a generated clip through the host's own audio output.

    The story asks for playback "routed through the DAW's audio engine", so this is
    mixed into the plugin's output in processBlock rather than opening a second
    device behind the host's back with an AudioDeviceManager.

    That makes this the first part of the plugin that touches the audio thread, so:

    - load() reads the file on the **message** thread and prepares the source there.
    - processBlock only ever pulls from an already-prepared source into an
      already-allocated buffer.
    - Swapping the loaded clip takes a juce::SpinLock, and the audio side uses
      **tryEnter**: if a load is mid-swap the block is skipped rather than blocked.
      A preview dropping a buffer during a load is inaudible; a priority inversion
      in the host's callback is not.
*/
class ClipPlayer
{
public:
    ClipPlayer();
    ~ClipPlayer();

    //==============================================================================
    /** From AudioProcessor::prepareToPlay. Allocates everything the audio thread
        will need. */
    void prepare (double sampleRate, int blockSize);
    void releaseResources();

    //==============================================================================
    /** Loads `file` ready to play. Message thread only — this opens and reads a file.
        @returns false if the file could not be read. */
    bool load (const juce::File& file);

    void play();
    void stop();

    /** Loads if needed and starts; stops instead if this clip is already playing. */
    bool toggle (const juce::File& file);

    bool isPlaying() const noexcept;
    juce::File getCurrentFile() const;

    /** Position in seconds, and the clip's length. */
    double getPosition() const;
    double getLength() const;

    //==============================================================================
    /** Mixes the playing clip into `buffer`. Audio thread; allocates nothing, and
        never blocks. */
    void addTo (juce::AudioBuffer<float>& buffer);

    /** The formats this can preview. Exposed so the results panel can reuse it for
        waveform thumbnails rather than registering a second set. */
    juce::AudioFormatManager& getFormatManager() noexcept     { return formats; }

private:
    juce::AudioFormatManager formats;
    juce::AudioTransportSource transport;
    std::unique_ptr<juce::AudioFormatReaderSource> readerSource;

    /** Guards the reader swap. The audio side only ever tryEnter()s it.
        Mutable so the const accessors can take it too. */
    mutable juce::SpinLock sourceLock;

    juce::AudioBuffer<float> scratch;
    double preparedSampleRate = 44100.0;
    int preparedBlockSize = 512;
    bool prepared = false;

    juce::File currentFile;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ClipPlayer)
};

} // namespace acemusic
