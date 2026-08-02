#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace acemusic
{

PluginProcessor::PluginProcessor()
    : PluginProcessor (ConnectionSettings::createPropertiesFile(), true)
{
}

PluginProcessor::PluginProcessor (std::unique_ptr<juce::PropertiesFile> propertiesToUse, bool probeOnLoad)
    : juce::AudioProcessor (BusesProperties()
                                .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
                                .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      properties (std::move (propertiesToUse)),
      connectionManager (backgroundQueue, properties.get()),
      generationManager (backgroundQueue, connectionManager, properties.get())
{
    if (probeOnLoad)
    {
        // Auto-connect on load. This only enqueues — the host is never blocked, and
        // the indicator updates when the probe comes back.
        connectionManager.autoConnect();
    }
}

PluginProcessor::~PluginProcessor() = default;

void PluginProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    // The clip preview is the only thing in this plugin that produces audio, and it
    // allocates everything it needs here rather than in the callback.
    clipPlayer.prepare (sampleRate, samplesPerBlock);
}

void PluginProcessor::releaseResources()
{
    clipPlayer.releaseResources();
}

bool PluginProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto& out = layouts.getMainOutputChannelSet();

    if (out != juce::AudioChannelSet::mono() && out != juce::AudioChannelSet::stereo())
        return false;

    // Input may be disabled entirely (AU allows this); otherwise it must match.
    const auto& in = layouts.getMainInputChannelSet();

    return in == out || in == juce::AudioChannelSet::disabled();
}

void PluginProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    // The one place the play head is read. Everything that wants the host tempo or
    // position takes a snapshot from HostSync instead of calling getPlayHead() off
    // the audio thread, which is a data race.
    hostSync.captureFrom (getPlayHead());

    // Passthrough. Any channel the host gave us as output but not as input has
    // undefined contents, so clear it.
    for (auto channel = getTotalNumInputChannels(); channel < getTotalNumOutputChannels(); ++channel)
        buffer.clear (channel, 0, buffer.getNumSamples());

    // Preview playback is mixed on top of the passthrough. It allocates nothing and
    // never blocks — it try-locks and skips the block if a clip is mid-load.
    clipPlayer.addTo (buffer);

    // No allocation, no blocking locks, no network here — ever. Server calls go
    // through getBackgroundQueue().
}

juce::AudioProcessorEditor* PluginProcessor::createEditor()
{
    return new PluginEditor (*this);
}

void PluginProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    // No persisted state yet; US-23.2 stores the server URL and model here.
    destData.reset();
}

void PluginProcessor::setStateInformation (const void*, int)
{
}

} // namespace acemusic

//==============================================================================
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new acemusic::PluginProcessor();
}
