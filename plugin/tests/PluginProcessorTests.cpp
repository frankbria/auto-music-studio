#include "PluginProcessor.h"

#include <atomic>

namespace
{
    /** A processor that never touches the user's real config and never probes on
        construction — these tests are about audio and layout, not the network. */
    std::unique_ptr<acemusic::PluginProcessor> makeOfflineProcessor()
    {
        return std::make_unique<acemusic::PluginProcessor> (nullptr, false);
    }
}

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
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            expectEquals (processor.getName(), juce::String ("AceMusic Studio"));
            expect (PluginProcessor::getPluginVersion().isNotEmpty(), "version is empty");
            expect (PluginProcessor::getPluginVersion() != "0.0.0",
                    "version fell back to the header default — ACEMUSIC_PLUGIN_VERSION was not defined");
            expect (processor.hasEditor(), "processor reports no editor");
        }

        beginTest ("is an effect, not a synth or MIDI processor");
        {
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            // acceptsMidi is true since US-24.3 — see its own test above. The plugin
            // still emits no MIDI and is not a MIDI effect.
            expect (! processor.producesMidi());
            expect (! processor.isMidiEffect());
            expectEquals (processor.getTailLengthSeconds(), 0.0);
        }

        beginTest ("accepts MIDI, for the Complete-mode sketch");
        {
            auto owned = makeOfflineProcessor();
            expect (owned->acceptsMidi(), "MIDI input is off, so Complete mode has no source");
            expect (! owned->producesMidi());
            expect (! owned->isMidiEffect());
        }

        beginTest ("the sidechain bus is optional, and every layout pluginval tries is accepted");
        {
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;

            using ChannelSet = juce::AudioChannelSet;

            // Off by default, so a host with no sidechain send is unaffected.
            expect (processor.getBus (true, 1) != nullptr, "no sidechain bus was declared");
            expect (! processor.getBus (true, 1)->isEnabled(),
                    "the sidechain is enabled by default, which changes existing sessions");
            expect (! processor.hasSidechainInput());

            for (const auto& sidechain : { ChannelSet::disabled(), ChannelSet::mono(), ChannelSet::stereo() })
            {
                expect (processor.setBusesLayout ({ { ChannelSet::stereo(), sidechain },
                                                    { ChannelSet::stereo() } }),
                        "rejected a sidechain layout pluginval will try: "
                            + sidechain.getDescription());
            }

            // Something the plugin genuinely cannot handle.
            expect (! processor.setBusesLayout ({ { ChannelSet::stereo(), ChannelSet::create5point1() },
                                                  { ChannelSet::stereo() } }),
                    "accepted a 5.1 sidechain");

            expect (processor.setBusesLayout ({ { ChannelSet::stereo(), ChannelSet::stereo() },
                                                { ChannelSet::stereo() } }));
            expect (processor.hasSidechainInput(), "an enabled sidechain was not reported");
        }

        beginTest ("audio still passes through untouched with MIDI and a sidechain present");
        {
            // The regression that matters most in US-24.3: capturing must not colour or
            // interrupt the audio the host is already sending through the plugin.
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;

            using ChannelSet = juce::AudioChannelSet;
            expect (processor.setBusesLayout ({ { ChannelSet::stereo(), ChannelSet::stereo() },
                                                { ChannelSet::stereo() } }));
            processor.prepareToPlay (44100.0, 512);

            // Main input on channels 0-1, sidechain on 2-3.
            juce::AudioBuffer<float> buffer (4, 512);
            buffer.clear();

            for (int i = 0; i < 512; ++i)
            {
                buffer.setSample (0, i, 0.25f);
                buffer.setSample (1, i, -0.25f);
                buffer.setSample (2, i, 0.9f);    // sidechain
                buffer.setSample (3, i, 0.9f);
            }

            juce::MidiBuffer midi;
            midi.addEvent (juce::MidiMessage::noteOn (1, 60, 0.8f), 0);

            processor.getMidiCapture().setRecording (true);
            processor.getSidechainCapture().setRecording (true);
            processor.processBlock (buffer, midi);

            for (int i = 0; i < 512; ++i)
            {
                expectWithinAbsoluteError (buffer.getSample (0, i), 0.25f, 1.0e-6f,
                                           "the main input was altered at sample " + juce::String (i));
                expectWithinAbsoluteError (buffer.getSample (1, i), -0.25f, 1.0e-6f,
                                           "the main input was altered at sample " + juce::String (i));
            }

            // And both captures actually saw something.
            processor.getMidiCapture().setRecording (false);
            processor.getSidechainCapture().setRecording (false);

            expect (processor.getMidiCapture().hasCapture(), "the MIDI note was not captured");
            expect (processor.getSidechainCapture().hasCapture(), "the sidechain was not captured");
            expectEquals ((int) processor.getSidechainCapture().getRecordedSamples(), 512);
        }

        beginTest ("supports mono and stereo, rejects mismatched layouts");
        {
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;

            using ChannelSet = juce::AudioChannelSet;

            // Three buses since US-24.3: main in, sidechain in, main out. The sidechain
            // is disabled here; its own layouts are covered below.
            const auto off = ChannelSet::disabled();

            expect (processor.setBusesLayout ({ { ChannelSet::stereo(), off }, { ChannelSet::stereo() } }),
                    "stereo in / stereo out rejected");
            expect (processor.setBusesLayout ({ { ChannelSet::mono(), off }, { ChannelSet::mono() } }),
                    "mono in / mono out rejected");
            expect (! processor.setBusesLayout ({ { ChannelSet::stereo(), off }, { ChannelSet::mono() } }),
                    "mismatched stereo in / mono out accepted");
            expect (! processor.setBusesLayout ({ { ChannelSet::create5point1(), off }, { ChannelSet::create5point1() } }),
                    "5.1 accepted");
        }

        beginTest ("passes audio through untouched");
        {
            constexpr int numChannels = 2;
            constexpr int numSamples  = 512;

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
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

            auto owned = makeOfflineProcessor();
            auto& processor = *owned;

            expect (processor.setBusesLayout ({ { juce::AudioChannelSet::disabled(),
                                                 juce::AudioChannelSet::disabled() },
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
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;

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
            auto owned = makeOfflineProcessor();
            auto& processor = *owned;
            std::atomic<bool> ran { false };

            processor.getBackgroundQueue().enqueue ([&] { ran = true; });

            expect (processor.getBackgroundQueue().waitForAll (5000), "queue did not drain");
            expect (ran.load(), "background task never ran");
        }
    }
};

static PluginProcessorTests pluginProcessorTests;

} // namespace acemusic
