#pragma once

#include "BackgroundTaskQueue.h"

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
    PluginProcessor();
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

    bool acceptsMidi() const override                         { return false; }
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
        server call in US-23.2 onwards goes through here. */
    BackgroundTaskQueue& getBackgroundQueue() noexcept        { return backgroundQueue; }

private:
    BackgroundTaskQueue backgroundQueue;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginProcessor)
};

} // namespace acemusic
