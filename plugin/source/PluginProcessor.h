#pragma once

#include "BackgroundTaskQueue.h"
#include "ClipPlayer.h"
#include "ConnectionManager.h"
#include "GenerationManager.h"
#include "HostSync.h"
#include "MidiCapture.h"
#include "SidechainCapture.h"

#include <juce_audio_processors/juce_audio_processors.h>

#ifndef ACEMUSIC_PLUGIN_VERSION
 #define ACEMUSIC_PLUGIN_VERSION "0.0.0"
#endif

namespace acemusic
{

/**
    The AceMusic Studio plugin.

    US-23.1 scope: it loads in a host, reports a stereo layout, passes audio
    through untouched, and owns the background queue that later stories use to
    talk to the ACE-Step server. processBlock() deliberately does nothing but
    forward audio — no allocation, no locks, no network.
*/
class PluginProcessor final : public juce::AudioProcessor
{
public:
    /** Production: reads/writes the user's real config file and probes on load. */
    PluginProcessor();

    /** Test seam. Lets a test point the settings at a throwaway file instead of the
        user's real config, and skip the load-time probe so constructing a processor
        never touches the network.
        @param propertiesToUse  settings store; may be null for "don't persist"
        @param probeOnLoad      whether to auto-connect, as the real plugin does */
    PluginProcessor (std::unique_ptr<juce::PropertiesFile> propertiesToUse, bool probeOnLoad);

    ~PluginProcessor() override;

    //==============================================================================
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    // Keep the double-precision overload reachable rather than hiding it; the
    // base class falls back to the float path.
    using juce::AudioProcessor::processBlock;

    //==============================================================================
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override                          { return true; }

    const juce::String getName() const override               { return "AceMusic Studio"; }
    static juce::String getPluginVersion()                    { return ACEMUSIC_PLUGIN_VERSION; }

    // US-24.3: MIDI is captured as a melodic sketch for Complete mode. The plugin still
    // produces no MIDI and is not a MIDI effect.
    bool acceptsMidi() const override                         { return true; }
    bool producesMidi() const override                        { return false; }
    bool isMidiEffect() const override                        { return false; }
    double getTailLengthSeconds() const override              { return 0.0; }

    int getNumPrograms() override                              { return 1; }
    int getCurrentProgram() override                           { return 0; }
    void setCurrentProgram (int) override                      {}
    const juce::String getProgramName (int) override           { return "Default"; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    /** Work queue for anything that must not run on the audio thread — every
        server call goes through here. */
    BackgroundTaskQueue& getBackgroundQueue() noexcept        { return backgroundQueue; }

    /** Server settings, connection status, and model list. Lives here rather than on
        the editor so it survives the plugin window being closed. */
    ConnectionManager& getConnectionManager() noexcept        { return connectionManager; }

    /** The current generation, for the same reason: a job runs for minutes and must
        outlive the plugin window. */
    GenerationManager& getGenerationManager() noexcept        { return generationManager; }

    /** Previews a generated clip through the host's output. Lives here because
        processBlock is what mixes it. */
    ClipPlayer& getClipPlayer() noexcept                      { return clipPlayer; }

    /** The host's tempo and transport position, sampled in processBlock. This is the
        only place anything reads the play head — see HostSync for why. */
    HostSync& getHostSync() noexcept                          { return hostSync; }

    /** MIDI played into the plugin, for Complete mode. */
    MidiCapture& getMidiCapture() noexcept                    { return midiCapture; }

    /** The sidechain input, for Cover and Repaint. */
    SidechainCapture& getSidechainCapture() noexcept          { return sidechainCapture; }

    /** True when the host actually gave us a sidechain bus with channels on it — a
        Cover or Repaint offered without one would be a dead end. */
    bool hasSidechainInput() const;

    /** The plugin config file, or null when running without one. */
    juce::PropertiesFile* getSettings() noexcept              { return properties.get(); }

private:
    // Declaration order is load-bearing: members are destroyed in reverse, so the
    // queue (declared first) is torn down last — after connectionManager is gone. A
    // probe still in flight then finds a cleared WeakReference and does nothing.
    BackgroundTaskQueue backgroundQueue;

    std::unique_ptr<juce::PropertiesFile> properties;
    ConnectionManager connectionManager;
    GenerationManager generationManager;
    ClipPlayer clipPlayer;
    HostSync hostSync;
    MidiCapture midiCapture;
    SidechainCapture sidechainCapture;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginProcessor)
};

} // namespace acemusic
