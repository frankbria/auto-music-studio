#include "PluginEditor.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

/** Drives the results panel through the real editor. Needs a display — on a headless
    Linux box run under `xvfb-run -a`. */
class ResultsPanelTests final : public juce::UnitTest
{
public:
    ResultsPanelTests()
        : juce::UnitTest ("ResultsPanel", "acemusic")
    {
    }

    bool pumpUntil (std::function<bool()> predicate, int timeoutMs = 20000)
    {
        auto* mm = juce::MessageManager::getInstance();
        const auto start = juce::Time::getMillisecondCounter();

        while (! predicate())
        {
            if ((juce::uint32) (juce::Time::getMillisecondCounter() - start) >= (juce::uint32) timeoutMs)
                return false;

            mm->runDispatchLoopUntil (10);
        }

        return true;
    }

    /** Real WAVs on disk, laid out the way GenerationManager writes them. */
    struct ScopedClips
    {
        explicit ScopedClips (int count = 2)
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-results-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();

            for (int i = 0; i < count; ++i)
                files.add (write (directory.getChildFile ("clip-" + juce::String (i + 1) + ".wav"),
                                  220.0 * (double) (i + 1)));
        }

        ~ScopedClips()  { directory.deleteRecursively(); }

        static juce::File write (const juce::File& file, double frequency)
        {
            const auto sampleRate = 44100.0;
            const auto numSamples = (int) sampleRate;   // one second

            juce::AudioBuffer<float> buffer (1, numSamples);

            for (int sample = 0; sample < numSamples; ++sample)
                buffer.setSample (0, sample,
                                  0.5f * std::sin (2.0f * juce::MathConstants<float>::pi
                                                   * (float) frequency * (float) sample / (float) sampleRate));

            juce::WavAudioFormat format;
            std::unique_ptr<juce::OutputStream> stream (file.createOutputStream());

            if (stream != nullptr)
            {
                const auto options = juce::AudioFormatWriterOptions{}
                                         .withSampleRate (sampleRate)
                                         .withNumChannels (1)
                                         .withBitsPerSample (16);

                if (auto writer = format.createWriterFor (stream, options))
                    writer->writeFromAudioSampleBuffer (buffer, 0, numSamples);
            }

            return file;
        }

        juce::File directory;
        juce::Array<juce::File> files;
    };

    /** Editor over an offline processor, with a generation driven to completion so
        the panel has real clips to show. */
    struct Harness
    {
        Harness()
            : processor (nullptr, false),
              editor (processor)
        {
            editor.setSize (720, 700);
            processor.prepareToPlay (44100.0, 512);
        }

        ResultsPanel& panel()          { return editor.getResultsPanel(); }
        GenerationManager& generation() { return processor.getGenerationManager(); }

        PluginProcessor processor;
        PluginEditor editor;
    };

    void runTest() override
    {
        beginTest ("shows nothing but an invitation before any generation");
        {
            Harness harness;

            expectEquals (harness.panel().getNumClipRows(), 0);
            expect (harness.panel().getStatusLabel().getText().containsIgnoreCase ("will appear"),
                    harness.panel().getStatusLabel().getText());
            expectEquals (harness.panel().getHistory().size(), 0);
        }

        beginTest ("AC: both generated clips get a row with a waveform");
        {
            ScopedClips clips;
            Harness harness;

            // Feed the panel real clips the way a finished generation would.
            harness.generation().setClipsForTesting (clips.files);

            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }),
                    "expected 2 clip rows, got " + juce::String (harness.panel().getNumClipRows()));

            for (int i = 0; i < 2; ++i)
            {
                auto* row = harness.panel().getClipRow (i);
                expect (row != nullptr);
                expectEquals (row->getFile().getFullPathName(), clips.files[i].getFullPathName());

                // AudioThumbnail loads on a background thread, so give it a moment.
                expect (pumpUntil ([row] { return row->hasWaveform(); }, 10000),
                        "waveform never loaded for clip " + juce::String (i + 1));
            }

            expect (harness.panel().getStatusLabel().getText().containsIgnoreCase ("drag"),
                    "did not tell the user they can drag: "
                        + harness.panel().getStatusLabel().getText());
        }

        beginTest ("AC (amended): a row hands the host the real file path to drop");
        {
            // VST3 cannot place audio on the timeline, so the panel exports by drag.
            // A real OS drag cannot be driven from a test, but what it would hand over
            // can be asserted exactly.
            ScopedClips clips;
            Harness harness;
            harness.generation().setClipsForTesting (clips.files);

            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            auto* row = harness.panel().getClipRow (0);
            const auto payload = row->getDragPayload();

            expectEquals (payload.size(), 1);
            expectEquals (payload[0], clips.files[0].getFullPathName());
            expect (juce::File (payload[0]).existsAsFile(), "the drag payload is not a real file");
        }

        beginTest ("AC: play starts the clip and stop silences it");
        {
            ScopedClips clips;
            Harness harness;
            harness.generation().setClipsForTesting (clips.files);

            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            auto* row = harness.panel().getClipRow (0);
            row->getPlayButton().triggerClick();

            expect (pumpUntil ([&] { return harness.processor.getClipPlayer().isPlaying(); }),
                    "the play button never started anything");
            expectEquals (harness.processor.getClipPlayer().getCurrentFile().getFullPathName(),
                          clips.files[0].getFullPathName());

            // And it is genuinely in the plugin's output, not just a flag.
            juce::AudioBuffer<float> buffer (2, 512);
            juce::MidiBuffer midi;
            float peak = 0.0f;

            for (int i = 0; i < 8; ++i)
            {
                buffer.clear();
                harness.processor.processBlock (buffer, midi);
                peak = juce::jmax (peak, buffer.getMagnitude (0, 512));
            }

            expect (peak > 0.1f, "the clip was not audible, peak was " + juce::String (peak));

            // The button becomes Stop while it plays.
            expect (pumpUntil ([row] { return row->getPlayButton().getButtonText() == "Stop"; }),
                    "the button never offered Stop");

            row->getPlayButton().triggerClick();
            expect (pumpUntil ([&] { return ! harness.processor.getClipPlayer().isPlaying(); }),
                    "the stop button never stopped anything");
        }

        beginTest ("playing the second clip switches away from the first");
        {
            ScopedClips clips;
            Harness harness;
            harness.generation().setClipsForTesting (clips.files);

            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            harness.panel().getClipRow (0)->getPlayButton().triggerClick();
            expect (pumpUntil ([&] { return harness.processor.getClipPlayer().isPlaying(); }));

            harness.panel().getClipRow (1)->getPlayButton().triggerClick();

            expect (pumpUntil ([&] {
                        return harness.processor.getClipPlayer().getCurrentFile()
                                   == clips.files[1];
                    }), "did not switch to the second clip");
            expect (harness.processor.getClipPlayer().isPlaying(), "stopped instead of switching");
        }

        beginTest ("AC: history keeps clips from earlier generations in this session");
        {
            ScopedClips first, second;
            Harness harness;

            harness.generation().setClipsForTesting (first.files);
            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));
            expectEquals (harness.panel().getHistory().size(), 2);

            harness.generation().setClipsForTesting (second.files);
            expect (pumpUntil ([&] {
                        return harness.panel().getClipRow (0) != nullptr
                            && harness.panel().getClipRow (0)->getFile() == second.files[0];
                    }), "the panel did not show the newer generation");

            // The rows show the latest run; history remembers both.
            expectEquals (harness.panel().getNumClipRows(), 2);
            expectEquals (harness.panel().getHistory().size(), 4,
                          "history lost the earlier generation");

            for (const auto& file : first.files)
                expect (harness.panel().getHistory().contains (file),
                        "history dropped " + file.getFileName());
        }

        beginTest ("a status broadcast does not rebuild rows that have not changed");
        {
            // Rebuilding would restart every waveform load, so the panel must only
            // rebuild when the clip set actually differs.
            ScopedClips clips;
            Harness harness;
            harness.generation().setClipsForTesting (clips.files);

            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));
            auto* rowBefore = harness.panel().getClipRow (0);

            // Same clips again, as a redundant broadcast would deliver.
            harness.generation().setClipsForTesting (clips.files);

            auto* mm = juce::MessageManager::getInstance();
            for (int i = 0; i < 10; ++i)
                mm->runDispatchLoopUntil (10);

            expect (harness.panel().getClipRow (0) == rowBefore,
                    "the panel rebuilt its rows for an unchanged clip set");
        }

        beginTest ("the panel reports the host playhead");
        {
            Harness harness;

            // No host transport in a test, so this must read as unavailable rather
            // than inventing a position — the point is that it never shows a fake
            // number. Wait for the readout's timer rather than guessing a pump count.
            expect (pumpUntil ([&] {
                        return harness.panel().getPlayheadLabel().getText().isNotEmpty();
                    }, 5000),
                    "the playhead readout never appeared");

            const auto text = harness.panel().getPlayheadLabel().getText();
            expect (text.containsIgnoreCase ("playhead"), "no playhead readout: " + text);
            expect (text.contains ("--"),
                    "invented a playhead position with no host transport: " + text);
        }

        beginTest ("closing the window while a clip plays does not stop it or crash");
        {
            // Playback lives on the processor, so it survives the editor.
            ScopedClips clips;

            PluginProcessor processor (nullptr, false);
            processor.prepareToPlay (44100.0, 512);
            processor.getGenerationManager().setClipsForTesting (clips.files);

            {
                PluginEditor editor (processor);
                editor.setSize (720, 700);

                expect (pumpUntil ([&] { return editor.getResultsPanel().getNumClipRows() == 2; }));
                editor.getResultsPanel().getClipRow (0)->getPlayButton().triggerClick();
                expect (pumpUntil ([&] { return processor.getClipPlayer().isPlaying(); }));
            }

            expect (processor.getClipPlayer().isPlaying(), "closing the window stopped playback");

            juce::AudioBuffer<float> buffer (2, 512);
            juce::MidiBuffer midi;
            buffer.clear();
            processor.processBlock (buffer, midi);

            processor.getClipPlayer().stop();
            expect (true, "survived the editor closing mid-playback");
        }
    }
};

static ResultsPanelTests resultsPanelTests;

} // namespace acemusic
