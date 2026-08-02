#include "FakePlayHead.h"
#include "PluginEditor.h"
#include "StubAceStepServer.h"
#include "TimeStretch.h"

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
            : settingsDir (makeTempDir()),
              processor (makeSettings (settingsDir), false),
              editor (processor)
        {
            editor.setSize (720, 700);
            processor.prepareToPlay (44100.0, 512);
        }

        ~Harness()  { settingsDir.deleteRecursively(); }

        static juce::File makeTempDir()
        {
            auto dir = juce::File::getSpecialLocation (juce::File::tempDirectory)
                           .getChildFile ("acemusic-panel-"
                                          + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            dir.createDirectory();
            return dir;
        }

        /** A real settings file in a throwaway directory: the cache path is a
            *persisted* setting, so a null store cannot exercise it — and the user's
            real config must never be touched by a test. */
        static std::unique_ptr<juce::PropertiesFile> makeSettings (const juce::File& dir)
        {
            juce::PropertiesFile::Options options;
            options.applicationName = "PanelTest";
            options.filenameSuffix  = ".settings";
            options.storageFormat   = juce::PropertiesFile::storeAsXML;

            auto settings = std::make_unique<juce::PropertiesFile> (dir.getChildFile ("PanelTest.settings"),
                                                                     options);

            // Point the clip cache at this throwaway directory. These tests used to
            // write into ClipCache::getDefaultDirectory() — the user's real cache.
            auto cacheDir = dir.getChildFile ("clips");
            cacheDir.createDirectory();
            settings->setValue (ClipCache::cachePathKey, cacheDir.getFullPathName());
            settings->saveIfNeeded();

            return settings;
        }

        /** Where this harness's cache lives. */
        juce::File cacheDirectory() const  { return settingsDir.getChildFile ("clips"); }

        juce::File settingsDir;

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

        beginTest ("AC: the browser lists past generations with their metadata");
        {
            // A fresh plugin with a cache already on disk — i.e. what the user sees
            // after closing and reopening, which session history alone cannot do.
            Harness harness;

            ScopedClips clips;
            auto run = harness.cacheDirectory().getChildFile ("20260730-120000-run1");
            run.createDirectory();

            for (int i = 0; i < clips.files.size(); ++i)
                clips.files[i].copyFileTo (run.getChildFile ("clip-" + juce::String (i + 1) + ".wav"));

            expect (ClipCache::writeMetadata (run, "cached prompt", "ace-step-1.5", 42.0));

            harness.panel().refreshCache();

            const auto& entries = harness.panel().getCacheEntries();
            expect (entries.size() >= 1, "the browser found nothing on disk");

            const ClipCache::Entry* found = nullptr;
            for (const auto& entry : entries)
                if (entry.prompt == "cached prompt")
                    found = &entry;

            expect (found != nullptr, "the cached generation was not listed");
            expectWithinAbsoluteError (found->durationSeconds, 42.0, 0.001);
            expectEquals (found->clips.size(), 2);

            expect (harness.panel().getCacheSizeLabel().getText().isNotEmpty(),
                    "no cache size reported");

            run.deleteRecursively();
        }

        beginTest ("AC: deleting from the browser removes it from disk and the list");
        {
            Harness harness;

            ScopedClips clips;
            auto run = harness.cacheDirectory().getChildFile ("20260730-130000-run7");
            run.createDirectory();
            clips.files[0].copyFileTo (run.getChildFile ("clip-1.wav"));
            expect (ClipCache::writeMetadata (run, "delete me", "m", 5.0));

            harness.panel().refreshCache();

            int row = -1;
            const auto& entries = harness.panel().getCacheEntries();
            for (int i = 0; i < entries.size(); ++i)
                if (entries.getReference (i).prompt == "delete me")
                    row = i;

            expect (row >= 0, "could not find the run to delete");

            harness.panel().getHistoryList().selectRow (row);
            expect (harness.panel().deleteSelectedEntry(), "delete reported failure");

            expect (! run.isDirectory(), "the run is still on disk");

            for (const auto& entry : harness.panel().getCacheEntries())
                expect (entry.prompt != "delete me", "still listed after deletion");
        }

        beginTest ("deleting the generation that is playing stops it first");
        {
            // Deleting the file underneath a playing clip is a bad time.
            Harness harness;

            ScopedClips clips;
            auto run = harness.cacheDirectory().getChildFile ("20260730-140000-run8");
            run.createDirectory();
            auto cached = run.getChildFile ("clip-1.wav");
            clips.files[0].copyFileTo (cached);
            expect (ClipCache::writeMetadata (run, "playing one", "m", 5.0));

            harness.panel().refreshCache();

            expect (harness.processor.getClipPlayer().load (cached));
            harness.processor.getClipPlayer().play();
            expect (harness.processor.getClipPlayer().isPlaying());

            int row = -1;
            const auto& entries = harness.panel().getCacheEntries();
            for (int i = 0; i < entries.size(); ++i)
                if (entries.getReference (i).prompt == "playing one")
                    row = i;

            expect (row >= 0);
            harness.panel().getHistoryList().selectRow (row);
            expect (harness.panel().deleteSelectedEntry());

            expect (! harness.processor.getClipPlayer().isPlaying(),
                    "kept playing a clip that was just deleted");
            expect (! run.isDirectory());
        }

        beginTest ("AC: a custom cache path typed into the panel is honoured");
        {
            Harness harness;

            auto custom = juce::File::getSpecialLocation (juce::File::tempDirectory)
                              .getChildFile ("acemusic-custom-"
                                             + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            custom.createDirectory();

            // A run that only exists in the custom location.
            ScopedClips clips;
            auto run = custom.getChildFile ("20260730-150000-run9");
            run.createDirectory();
            clips.files[0].copyFileTo (run.getChildFile ("clip-1.wav"));
            expect (ClipCache::writeMetadata (run, "only in the custom path", "m", 7.0));

            harness.panel().getCachePathEditor().setText (custom.getFullPathName(), false);
            harness.panel().commitCachePath();

            expectEquals (harness.panel().getCache().getDirectory().getFullPathName(),
                          custom.getFullPathName());

            auto found = false;
            for (const auto& entry : harness.panel().getCacheEntries())
                if (entry.prompt == "only in the custom path")
                    found = true;

            expect (found, "the browser did not read the custom cache path");

            // Blank resets to the default rather than pointing at the filesystem root.
            harness.panel().getCachePathEditor().setText ("", false);
            harness.panel().commitCachePath();
            expectEquals (harness.panel().getCache().getDirectory().getFullPathName(),
                          ClipCache::getDefaultDirectory().getFullPathName());

            custom.deleteRecursively();
        }

        beginTest ("Clear cache stops a clip that is playing from inside it");
        {
            // Same hazard as deleting one run, and it was missing here: on Windows the
            // open handle makes the delete fail outright, elsewhere the clip plays on
            // from an unlinked file until the read-ahead drains.
            Harness harness;

            ScopedClips clips;
            auto run = harness.cacheDirectory().getChildFile ("20260730-160000-run11");
            run.createDirectory();
            auto cached = run.getChildFile ("clip-1.wav");
            clips.files[0].copyFileTo (cached);
            expect (ClipCache::writeMetadata (run, "playing during clear", "m", 5.0));

            harness.panel().refreshCache();
            expect (harness.panel().getCacheEntries().size() >= 1);

            expect (harness.processor.getClipPlayer().load (cached));
            harness.processor.getClipPlayer().play();
            expect (harness.processor.getClipPlayer().isPlaying());

            harness.panel().getClearCacheButton().triggerClick();
            expect (pumpUntil ([&] { return ! harness.processor.getClipPlayer().isPlaying(); }),
                    "Clear cache deleted the clip out from under the player");

            expect (! run.isDirectory(), "Clear cache did not remove the run");
            expectEquals (harness.panel().getCacheEntries().size(), 0);
        }

        beginTest ("the ordinary flow works: click a row, click Delete");
        {
            // The previous tests called deleteSelectedEntry() directly, so they
            // covered the function but never the button a user actually presses —
            // which was greyed out, because nothing enabled it on selection.
            Harness harness;

            ScopedClips clips;
            auto run = harness.cacheDirectory().getChildFile ("20260730-170000-run12");
            run.createDirectory();
            clips.files[0].copyFileTo (run.getChildFile ("clip-1.wav"));
            expect (ClipCache::writeMetadata (run, "click me", "m", 5.0));

            harness.panel().refreshCache();
            expect (harness.panel().getCacheEntries().size() >= 1);

            // Nothing selected yet.
            expect (! harness.panel().getDeleteButton().isEnabled(),
                    "Delete was live with no selection");

            int row = -1;
            const auto& entries = harness.panel().getCacheEntries();
            for (int i = 0; i < entries.size(); ++i)
                if (entries.getReference (i).prompt == "click me")
                    row = i;

            expect (row >= 0);
            harness.panel().getHistoryList().selectRow (row);

            expect (pumpUntil ([&] { return harness.panel().getDeleteButton().isEnabled(); }, 3000),
                    "selecting a row left Delete greyed out");

            harness.panel().getDeleteButton().triggerClick();

            expect (pumpUntil ([&] { return ! run.isDirectory(); }, 3000),
                    "the Delete button did not remove the run");
            expect (! harness.panel().getDeleteButton().isEnabled(),
                    "Delete stayed live after the selection was removed");
        }

        beginTest ("delete does nothing with no selection");
        {
            Harness harness;
            harness.panel().refreshCache();
            harness.panel().getHistoryList().deselectAllRows();

            expect (! harness.panel().deleteSelectedEntry(),
                    "claimed to delete something with nothing selected");
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

        //======================================================================
        // US-24.1 — tempo matching on insertion.

        beginTest ("AC: a 118 BPM clip is dropped into a 120 BPM project already stretched");
        {
            ScopedClips clips;
            Harness harness;

            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            harness.generation().setClipsForTesting (clips.files, 118);
            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            auto* row = harness.panel().getClipRow (0);

            expect (pumpUntil ([&] { return row->getDragFile() != row->getFile(); }, 20000),
                    "the clip was never tempo-matched to the host");

            const auto payload = row->getDragPayload();
            expectEquals (payload.size(), 1);

            const juce::File dropped { payload[0] };
            expect (dropped.existsAsFile(), "the tempo-matched drop is not a real file");
            expect (dropped != clips.files[0], "the drop was still the unstretched clip");
            expect (dropped == TimeStretch::getMatchedFileFor (clips.files[0], 120.0),
                    "unexpected match path: " + dropped.getFullPathName());

            // And it really is shorter, in the ratio the tempo change implies.
            juce::AudioFormatManager formats;
            formats.registerBasicFormats();
            std::unique_ptr<juce::AudioFormatReader> reader (formats.createReaderFor (dropped));
            expect (reader != nullptr, "the tempo-matched drop is not readable audio");

            const auto expected = (juce::int64) std::llround (44100.0 / TimeStretch::rateFor (118.0, 120.0));
            expect (std::abs (reader->lengthInSamples - expected) <= 1,
                    "dropped clip was " + juce::String (reader->lengthInSamples)
                        + " samples, expected " + juce::String (expected));
        }

        beginTest ("tempo-matched copies do not show up as extra clips in the cache browser");
        {
            // The cache browser lists *.wav in a run directory. A tempo match written
            // beside the clip would be counted as a third clip of a two-clip run, and
            // would come back as one when the generation is reopened from the cache.
            Harness harness;

            const auto run = harness.cacheDirectory().getChildFile ("run-1");
            run.createDirectory();

            juce::Array<juce::File> clips;
            clips.add (ScopedClips::write (run.getChildFile ("clip-1.wav"), 220.0));
            clips.add (ScopedClips::write (run.getChildFile ("clip-2.wav"), 440.0));
            ClipCache::writeMetadata (run, "a prompt", "a-model", 1.0);

            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            harness.generation().setClipsForTesting (clips, 118);
            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));
            expect (pumpUntil ([&] { return harness.panel().getClipRow (0)->getDragFile()
                                             != harness.panel().getClipRow (0)->getFile(); }, 20000),
                    "never tempo-matched, so this proves nothing");
            expect (pumpUntil ([&] { return harness.panel().getClipRow (1)->getDragFile()
                                             != harness.panel().getClipRow (1)->getFile(); }, 20000));

            const auto entry = ClipCache::readEntry (run);
            expectEquals (entry.clips.size(), 2,
                          "the cache browser counted the tempo-matched copies as clips");

            // It is still on disk and still accounted for, just not listed as a clip.
            expect (TimeStretch::getMatchedFileFor (clips[0], 120.0).existsAsFile());
            expect (entry.sizeInBytes > clips[0].getSize() + clips[1].getSize(),
                    "the tempo matches were not counted in the run's size on disk");
        }

        beginTest ("a clip already at the host tempo is dropped untouched");
        {
            ScopedClips clips;
            Harness harness;

            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            harness.generation().setClipsForTesting (clips.files, 120);
            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            auto* row = harness.panel().getClipRow (0);

            // Give the panel several ticks to do the wrong thing.
            expect (! pumpUntil ([&] { return row->getDragFile() != row->getFile(); }, 2000),
                    "a clip already at tempo was stretched anyway");
            expectEquals (row->getDragPayload()[0], clips.files[0].getFullPathName());
            expect (! TimeStretch::getMatchedFileFor (clips.files[0], 120.0).existsAsFile(),
                    "a pointless tempo match was written to disk");
        }

        beginTest ("an Auto-BPM generation or a silent host leaves the clip alone");
        {
            for (const auto scenario : { 0, 1 })
            {
                ScopedClips clips;
                Harness harness;

                test::FakePlayHead playHead;

                // 0: the host has a tempo but the generation asked for Auto BPM, so the
                //    clip's own tempo is unknown and guessing would be worse than nothing.
                // 1: the generation asked for 118 but the host publishes no tempo.
                playHead.reportsPosition = scenario == 0;
                playHead.bpm = 120.0;
                harness.processor.getHostSync().captureFrom (&playHead);

                harness.generation().setClipsForTesting (clips.files, scenario == 0 ? -1 : 118);
                expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

                auto* row = harness.panel().getClipRow (0);

                expect (! pumpUntil ([&] { return row->getDragFile() != row->getFile(); }, 1500),
                        "scenario " + juce::String (scenario) + ": stretched against an unknown tempo");
                expectEquals (row->getDragPayload()[0], clips.files[0].getFullPathName());
            }
        }

        beginTest ("a host tempo change re-matches the clip to the new tempo");
        {
            ScopedClips clips;
            Harness harness;

            test::FakePlayHead playHead;
            playHead.bpm = 120.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            harness.generation().setClipsForTesting (clips.files, 118);
            expect (pumpUntil ([&] { return harness.panel().getNumClipRows() == 2; }));

            auto* row = harness.panel().getClipRow (0);
            expect (pumpUntil ([&] { return row->getDragFile() != row->getFile(); }, 20000),
                    "never matched to 120");

            playHead.bpm = 140.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            expect (pumpUntil ([&] { return row->getDragFile()
                                             == TimeStretch::getMatchedFileFor (clips.files[0], 140.0); },
                               20000),
                    "the drop stayed matched to the old tempo: " + row->getDragFile().getFullPathName());

            // And going back to the clip's own tempo hands the original over again.
            playHead.bpm = 118.0;
            harness.processor.getHostSync().captureFrom (&playHead);

            expect (pumpUntil ([&] { return row->getDragFile() == row->getFile(); }, 20000),
                    "the original was not restored when the host matched the clip");
        }
    }
};

static ResultsPanelTests resultsPanelTests;

} // namespace acemusic
