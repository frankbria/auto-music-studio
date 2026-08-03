#include "AudioIo.h"

namespace acemusic
{
namespace AudioIo
{

bool writeWav (const juce::File& destination,
               const juce::AudioBuffer<float>& buffer,
               double sampleRate,
               int bitsPerSample)
{
    if (buffer.getNumSamples() <= 0 || buffer.getNumChannels() <= 0 || sampleRate <= 0.0)
        return false;

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
                                                       .withNumChannels (buffer.getNumChannels())
                                                       .withBitsPerSample (bitsPerSample));

        if (writer == nullptr)
            return false;

        if (! writer->writeFromAudioSampleBuffer (buffer, 0, buffer.getNumSamples()))
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

} // namespace AudioIo
} // namespace acemusic
