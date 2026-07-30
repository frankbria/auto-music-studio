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
      generationManager (backgroundQueue, connectionManager)
{
    if (probeOnLoad)
    {
        // Auto-connect on load. This only enqueues — the host is never blocked, and
        // the indicator updates when the probe comes back.
        connectionManager.autoConnect();
    }
}

PluginProcessor::~PluginProcessor() = default;

void PluginProcessor::prepareToPlay (double, int)
{
    // Nothing to allocate yet — generation happens off the audio thread and
    // lands as clips in the host, not as a live signal path.
}

void PluginProcessor::releaseResources()
{
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

    // Passthrough. Any channel the host gave us as output but not as input has
    // undefined contents, so clear it.
    for (auto channel = getTotalNumInputChannels(); channel < getTotalNumOutputChannels(); ++channel)
        buffer.clear (channel, 0, buffer.getNumSamples());

    // No allocation, no locks, no network here — ever. Server calls go through
    // getBackgroundQueue().
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
