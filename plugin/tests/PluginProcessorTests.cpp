#include "PluginProcessor.h"

namespace acemusic
{

class PluginProcessorTests final : public juce::UnitTest
{
public:
    PluginProcessorTests()
        : juce::UnitTest ("PluginProcessor", "acemusic")
    {
    }

    void runTest() override
    {
        beginTest ("identifies itself");
        {
            PluginProcessor processor;
            expectEquals (processor.getName(), juce::String ("AceMusic Studio"));
            expect (PluginProcessor::getPluginVersion().isNotEmpty(), "version is empty");
            expect (PluginProcessor::getPluginVersion() != "0.0.0",
                    "version fell back to the header default — ACEMUSIC_PLUGIN_VERSION was not defined");
            expect (processor.hasEditor(), "processor reports no editor");
        }

        beginTest ("is an effect, not a synth or MIDI processor");
        {
            PluginProcessor processor;
            expect (! processor.acceptsMidi());
            expect (! processor.producesMidi());
            expect (! processor.isMidiEffect());
            expectEquals (processor.getTailLengthSeconds(), 0.0);
        }

        beginTest ("supports mono and stereo, rejects mismatched layouts");
        {
            PluginProcessor processor;

            using ChannelSet = juce::AudioChannelSet;

            expect (processor.setBusesLayout ({ { ChannelSet::stereo() }, { ChannelSet::stereo() } }),
                    "stereo in / stereo out rejected");
            expect (processor.setBusesLayout ({ { ChannelSet::mono() }, { ChannelSet::mono() } }),
                    "mono in / mono out rejected");
            expect (! processor.setBusesLayout ({ { ChannelSet::stereo() }, { ChannelSet::mono() } }),
                    "mismatched stereo in / mono out accepted");
            expect (! processor.setBusesLayout ({ { ChannelSet::create5point1() }, { ChannelSet::create5point1() } }),
                    "5.1 accepted");
        }

        beginTest ("passes audio through untouched");
        {
            constexpr int numChannels = 2;
            constexpr int numSamples  = 512;

            PluginProcessor processor;
            processor.setPlayConfigDetails (numChannels, numChannels, 48000.0, numSamples);
            processor.prepareToPlay (48000.0, numSamples);

            juce::AudioBuffer<float> buffer { numChannels, numSamples };
            juce::AudioBuffer<float> expected { numChannels, numSamples };

            juce::Random random { 1234 };

            for (int channel = 0; channel < numChannels; ++channel)
            {
                for (int sample = 0; sample < numSamples; ++sample)
                {
                    const auto value = random.nextFloat() * 2.0f - 1.0f;
                    buffer.setSample (channel, sample, value);
                    expected.setSample (channel, sample, value);
                }
            }

            juce::MidiBuffer midi;
            processor.processBlock (buffer, midi);

            for (int channel = 0; channel < numChannels; ++channel)
                for (int sample = 0; sample < numSamples; ++sample)
                    expectEquals (buffer.getSample (channel, sample),
                                  expected.getSample (channel, sample),
                                  "sample altered at channel " + juce::String (channel)
                                      + ", index " + juce::String (sample));

            processor.releaseResources();
        }

        beginTest ("clears output channels the host did not supply as inputs");
        {
            // The only layout with more outputs than inputs that this processor
            // accepts is a disabled input bus (AU hosts do instantiate this).
            // Those output channels arrive with undefined contents and must be
            // silenced rather than passed on as garbage.
            constexpr int numSamples = 128;

            PluginProcessor processor;

            expect (processor.setBusesLayout ({ { juce::AudioChannelSet::disabled() },
                                               { juce::AudioChannelSet::stereo() } }),
                    "disabled input / stereo output rejected");
            expectEquals (processor.getTotalNumInputChannels(), 0);
            expectEquals (processor.getTotalNumOutputChannels(), 2);

            processor.prepareToPlay (48000.0, numSamples);

            juce::AudioBuffer<float> buffer { 2, numSamples };

            for (int channel = 0; channel < 2; ++channel)
                for (int sample = 0; sample < numSamples; ++sample)
                    buffer.setSample (channel, sample, 0.9f); // stale garbage

            juce::MidiBuffer midi;
            processor.processBlock (buffer, midi);

            for (int channel = 0; channel < 2; ++channel)
                expectEquals (buffer.getMagnitude (channel, 0, numSamples), 0.0f,
                              "output channel " + juce::String (channel) + " was not cleared");
        }

        beginTest ("state round-trips without state to store");
        {
            PluginProcessor processor;

            juce::MemoryBlock state;
            processor.getStateInformation (state);

            // No persisted settings until US-23.2 — but a host will still call
            // both, and neither may crash or leave junk behind.
            expectEquals ((int) state.getSize(), 0);
            processor.setStateInformation (state.getData(), (int) state.getSize());
            processor.setStateInformation (nullptr, 0);
        }

        beginTest ("exposes a background queue that runs work off the caller's thread");
        {
            PluginProcessor processor;
            std::atomic<bool> ran { false };

            processor.getBackgroundQueue().enqueue ([&] { ran = true; });

            expect (processor.getBackgroundQueue().waitForAll (5000), "queue did not drain");
            expect (ran.load(), "background task never ran");
        }
    }
};

static PluginProcessorTests pluginProcessorTests;

} // namespace acemusic
