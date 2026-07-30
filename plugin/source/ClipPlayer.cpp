#include "ClipPlayer.h"

namespace acemusic
{

ClipPlayer::ClipPlayer()
{
    formats.registerBasicFormats();
}

ClipPlayer::~ClipPlayer()
{
    transport.setSource (nullptr);
}

void ClipPlayer::prepare (double sampleRate, int blockSize)
{
    preparedSampleRate = sampleRate;
    preparedBlockSize  = juce::jmax (1, blockSize);

    // Everything the audio thread touches is sized here, on the message thread.
    scratch.setSize (2, preparedBlockSize, false, true, true);
    transport.prepareToPlay (preparedBlockSize, preparedSampleRate);

    prepared = true;
}

void ClipPlayer::releaseResources()
{
    prepared = false;
    transport.releaseResources();
}

bool ClipPlayer::load (const juce::File& file)
{
    if (! file.existsAsFile())
        return false;

    std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (file));

    if (reader == nullptr)
        return false;

    auto newSource = std::make_unique<juce::AudioFormatReaderSource> (reader.release(), true);

    if (prepared)
        newSource->prepareToPlay (preparedBlockSize, preparedSampleRate);

    {
        // The audio thread only tryEnter()s this, so holding it briefly here costs a
        // skipped block at worst.
        const juce::SpinLock::ScopedLockType lock (sourceLock);

        transport.setSource (nullptr);
        readerSource = std::move (newSource);
        transport.setSource (readerSource.get(),
                             0, nullptr,
                             readerSource->getAudioFormatReader()->sampleRate);
        transport.setPosition (0.0);
        currentFile = file;
    }

    return true;
}

void ClipPlayer::play()
{
    const juce::SpinLock::ScopedLockType lock (sourceLock);

    if (readerSource == nullptr)
        return;

    // Restart from the top if the previous play ran to the end.
    if (transport.hasStreamFinished() || transport.getCurrentPosition() >= transport.getLengthInSeconds())
        transport.setPosition (0.0);

    transport.start();
}

void ClipPlayer::stop()
{
    const juce::SpinLock::ScopedLockType lock (sourceLock);
    transport.stop();
    transport.setPosition (0.0);
}

bool ClipPlayer::toggle (const juce::File& file)
{
    if (isPlaying() && getCurrentFile() == file)
    {
        stop();
        return true;
    }

    if (getCurrentFile() != file && ! load (file))
        return false;

    play();
    return true;
}

bool ClipPlayer::isPlaying() const noexcept
{
    return transport.isPlaying();
}

juce::File ClipPlayer::getCurrentFile() const
{
    const juce::SpinLock::ScopedLockType lock (sourceLock);
    return currentFile;
}

double ClipPlayer::getPosition() const
{
    return transport.getCurrentPosition();
}

double ClipPlayer::getLength() const
{
    return transport.getLengthInSeconds();
}

void ClipPlayer::addTo (juce::AudioBuffer<float>& buffer)
{
    if (! prepared || ! transport.isPlaying())
        return;

    // Never block the host's callback: if a load is swapping the source right now,
    // skip this block instead of waiting on it.
    const juce::SpinLock::ScopedTryLockType lock (sourceLock);

    if (! lock.isLocked() || readerSource == nullptr)
        return;

    const auto numSamples = buffer.getNumSamples();

    // prepare() sized the scratch buffer; a host handing us a bigger block than it
    // promised would mean allocating here, so take what we can rather than resize.
    const auto usable = juce::jmin (numSamples, scratch.getNumSamples());

    if (usable <= 0)
        return;

    juce::AudioSourceChannelInfo info (&scratch, 0, usable);
    transport.getNextAudioBlock (info);

    // No mono upmix needed here: prepare() always sizes the scratch buffer to two
    // channels, and AudioFormatReaderSource duplicates a mono file across them. A
    // mutation pass proved an explicit upmix branch was unreachable, so it is gone
    // rather than sitting there looking load-bearing.
    const auto channelsToMix = juce::jmin (buffer.getNumChannels(), scratch.getNumChannels());

    for (int channel = 0; channel < channelsToMix; ++channel)
        buffer.addFrom (channel, 0, scratch, channel, 0, usable);
}

} // namespace acemusic
