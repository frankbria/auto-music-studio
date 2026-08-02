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
                                .withOutput ("Output", juce::AudioChannelSet::stereo(), true)
                                // Off by default: a host with no sidechain send must load
                                // the plugin exactly as it did before US-24.3, and existing
                                // sessions must not change shape underneath the user.
                                .withInput  ("Sidechain", juce::AudioChannelSet::stereo(), false)),
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

    // Both captures take all the memory they will ever use here, for the same reason.
    midiCapture.prepare (sampleRate);
    sidechainCapture.prepare (sampleRate, juce::jmax (1, getChannelCountOfBus (true, 1)));
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

    if (in != out && in != juce::AudioChannelSet::disabled())
        return false;

    // The sidechain is optional and independent of the main pair: absent, mono or
    // stereo. pluginval fuzzes every combination of these, so all three are accepted
    // rather than only the one the UI happens to use.
    if (layouts.inputBuses.size() > 1)
    {
        const auto& sidechain = layouts.getChannelSet (true, 1);

        if (sidechain != juce::AudioChannelSet::disabled()
            && sidechain != juce::AudioChannelSet::mono()
            && sidechain != juce::AudioChannelSet::stereo())
        {
            return false;
        }
    }

    return true;
}

bool PluginProcessor::hasSidechainInput() const
{
    return getChannelCountOfBus (true, 1) > 0;
}

void PluginProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;

    // The one place the play head is read. Everything that wants the host tempo or
    // position takes a snapshot from HostSync instead of calling getPlayHead() off
    // the audio thread, which is a data race.
    hostSync.captureFrom (getPlayHead());

    // Both of these only record when armed, and neither allocates or blocks. The MIDI
    // side pushes note events into a lock-free FIFO — nothing is synthesised here.
    midiCapture.processBlock (midi, buffer.getNumSamples());

    if (auto* sidechain = getBus (true, 1); sidechain != nullptr && sidechain->isEnabled())
    {
        const auto sidechainBuffer = sidechain->getBusBuffer (buffer);
        sidechainCapture.processBlock (sidechainBuffer);
    }

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
