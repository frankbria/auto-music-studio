#include "ClipCache.h"

namespace acemusic
{

class ClipCacheTests final : public juce::UnitTest
{
public:
    ClipCacheTests()
        : juce::UnitTest ("ClipCache", "acemusic")
    {
    }

    /** A settings file and a cache directory, both thrown away afterwards. */
    struct ScopedCache
    {
        ScopedCache()
        {
            root = juce::File::getSpecialLocation (juce::File::tempDirectory)
                       .getChildFile ("acemusic-cache-"
                                      + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            root.createDirectory();

            cacheDir = root.getChildFile ("clips");
            cacheDir.createDirectory();

            juce::PropertiesFile::Options options;
            options.applicationName = "CacheTest";
            options.filenameSuffix  = ".settings";
            options.storageFormat   = juce::PropertiesFile::storeAsXML;

            properties = std::make_unique<juce::PropertiesFile> (root.getChildFile ("CacheTest.settings"),
                                                                 options);

            cache = std::make_unique<ClipCache> (properties.get());
            cache->setDirectory (cacheDir);
        }

        ~ScopedCache()
        {
            cache.reset();
            properties.reset();
            root.deleteRecursively();
        }

        /** Writes a run directory with `numClips` real (tiny) wav files.

            The directory is named the way the plugin names its runs, because deletion
            is gated on that shape — a fixture using arbitrary names would be testing
            something the plugin never produces. `label` is kept only to make the test
            body readable. */
        juce::File makeRun (const juce::String& label, int numClips = 2,
                            const juce::String& prompt = {},
                            double duration = 30.0)
        {
            juce::ignoreUnused (label);

            auto run = cacheDir.getChildFile (juce::String ("20260730-1200")
                                                  + juce::String (runCounter).paddedLeft ('0', 2)
                                                  + "-run" + juce::String (runCounter));
            ++runCounter;
            run.createDirectory();

            for (int i = 0; i < numClips; ++i)
                writeWav (run.getChildFile ("clip-" + juce::String (i + 1) + ".wav"));

            if (prompt.isNotEmpty())
                ClipCache::writeMetadata (run, prompt, "ace-step-1.5", duration);

            return run;
        }

        static void writeWav (const juce::File& file)
        {
            const auto sampleRate = 8000.0;
            juce::AudioBuffer<float> buffer (1, 800);
            buffer.clear();

            juce::WavAudioFormat format;
            std::unique_ptr<juce::OutputStream> stream (file.createOutputStream());

            if (stream != nullptr)
            {
                const auto options = juce::AudioFormatWriterOptions{}
                                         .withSampleRate (sampleRate)
                                         .withNumChannels (1)
                                         .withBitsPerSample (16);

                if (auto writer = format.createWriterFor (stream, options))
                    writer->writeFromAudioSampleBuffer (buffer, 0, buffer.getNumSamples());
            }
        }

        juce::File root, cacheDir;
        int runCounter = 1;
        std::unique_ptr<juce::PropertiesFile> properties;
        std::unique_ptr<ClipCache> cache;
    };

    void runTest() override
    {
        beginTest ("the default is a hidden cache location, not a visible home folder");
        {
            const auto def = ClipCache::getDefaultDirectory();
            expect (def.getFullPathName().isNotEmpty());

           #if JUCE_LINUX || JUCE_BSD
            // The issue proposes ~/ACEStepPlugin/cache/. That would drop a visible
            // directory into $HOME — the same bug fixed for the settings file in
            // US-23.2 — so the default is the XDG cache tree instead.
            const auto home = juce::File::getSpecialLocation (juce::File::userHomeDirectory);
            expectEquals (def.getFullPathName(),
                          home.getChildFile (".cache/AutoMusicStudio/clips").getFullPathName());
            expect (! def.isAChildOf (home) || def.getFullPathName().contains ("/."),
                    "the default cache is a visible directory in $HOME: " + def.getFullPathName());
           #endif
        }

        beginTest ("AC: a custom cache path is respected, and clearing it restores the default");
        {
            ScopedCache scoped;

            expectEquals (scoped.cache->getDirectory().getFullPathName(),
                          scoped.cacheDir.getFullPathName());

            // A fresh cache over the same settings sees the same path — this is what
            // "respected after configuration change" means across sessions.
            ClipCache reopened (scoped.properties.get());
            expectEquals (reopened.getDirectory().getFullPathName(),
                          scoped.cacheDir.getFullPathName());

            scoped.cache->setDirectory (juce::File());
            expectEquals (scoped.cache->getDirectory().getFullPathName(),
                          ClipCache::getDefaultDirectory().getFullPathName(),
                          "clearing the path did not restore the default");
        }

        beginTest ("an empty cache lists nothing and reports zero");
        {
            ScopedCache scoped;

            expectEquals (scoped.cache->listEntries().size(), 0);
            expectEquals ((int) scoped.cache->getTotalSizeInBytes(), 0);
        }

        beginTest ("AC: the browser lists runs with the metadata they were made with");
        {
            ScopedCache scoped;
            scoped.makeRun ("20260730-100000-run1", 2, "warm analogue synth pad", 45.0);

            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 1);

            const auto& entry = entries.getReference (0);
            expect (entry.hasMetadata, "the sidecar was not read back");
            expectEquals (entry.prompt, juce::String ("warm analogue synth pad"));
            expectEquals (entry.model, juce::String ("ace-step-1.5"));
            expectWithinAbsoluteError (entry.durationSeconds, 45.0, 0.001);
            expectEquals (entry.clips.size(), 2);
            expect (entry.sizeInBytes > 0, "reported a zero-byte run");

            // A real timestamp, not the epoch.
            expect (entry.created.toMilliseconds() > 0, "no creation time");
        }

        beginTest ("a run without a sidecar still lists rather than disappearing");
        {
            // Losing a whole generation because its metadata went missing would be
            // worse than showing it with a blank prompt.
            ScopedCache scoped;
            scoped.makeRun ("orphan", 2);   // no metadata written

            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 1, "a run without metadata was dropped");
            expect (! entries.getReference (0).hasMetadata);
            expect (entries.getReference (0).prompt.isEmpty());
            expectEquals (entries.getReference (0).clips.size(), 2);
        }

        beginTest ("a corrupt sidecar does not take the whole listing down");
        {
            ScopedCache scoped;
            auto run = scoped.makeRun ("broken", 1);
            run.getChildFile ("meta.json").replaceWithText ("{not json at all");

            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 1, "a corrupt sidecar hid the run");
            expectEquals (entries.getReference (0).clips.size(), 1);
        }

        beginTest ("a directory with no audio is not listed as a generation");
        {
            ScopedCache scoped;
            scoped.cacheDir.getChildFile ("20260730-120099-run99").createDirectory();
            scoped.makeRun ("real-run", 1, "something", 10.0);

            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 1, "listed a directory containing no clips");
        }

        beginTest ("runs come back newest first");
        {
            // Five runs, not two. Directory iteration order is not specified, so with
            // only a pair a broken sort can come out right by luck — a mutation pass
            // proved exactly that. Five makes an accidental pass a 1-in-120 shot, and
            // the assertion is the real invariant (non-increasing by creation time)
            // rather than one hardcoded position.
            ScopedCache scoped;

            juce::StringArray expectedNewestFirst;

            for (int i = 0; i < 5; ++i)
            {
                const auto prompt = "run " + juce::String (i);
                scoped.makeRun ("dir-" + juce::String (i), 1, prompt, 10.0);
                expectedNewestFirst.insert (0, prompt);   // newest ends up first
                juce::Thread::sleep (25);
            }

            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 5);

            for (int i = 1; i < entries.size(); ++i)
            {
                expect (entries.getReference (i - 1).created >= entries.getReference (i).created,
                        "entries are not ordered newest-first at index " + juce::String (i));
            }

            juce::StringArray actual;
            for (const auto& entry : entries)
                actual.add (entry.prompt);

            expectEquals (actual.joinIntoString (", "), expectedNewestFirst.joinIntoString (", "),
                          "the order does not match creation order reversed");
        }

        beginTest ("AC: the reported size matches what is actually on disk");
        {
            ScopedCache scoped;
            scoped.makeRun ("run1", 2, "one", 10.0);
            scoped.makeRun ("run2", 3, "two", 10.0);

            juce::int64 actual = 0;
            for (const auto& item : juce::RangedDirectoryIterator (scoped.cacheDir, true, "*",
                                                                   juce::File::findFiles))
                actual += item.getFile().getSize();

            expect (actual > 0, "the fixture wrote nothing");
            expectEquals ((int) scoped.cache->getTotalSizeInBytes(), (int) actual,
                          "the reported cache size does not match the bytes on disk");

            const auto description = scoped.cache->getTotalSizeDescription();
            expect (description.isNotEmpty() && ! description.startsWith ("0 "),
                    "size description looks wrong: " + description);
        }

        beginTest ("AC: deleting a run removes it from disk and from the listing");
        {
            ScopedCache scoped;
            scoped.makeRun ("keep", 1, "keep me", 10.0);
            auto doomed = scoped.makeRun ("delete", 2, "delete me", 10.0);

            expectEquals (scoped.cache->listEntries().size(), 2);
            const auto sizeBefore = scoped.cache->getTotalSizeInBytes();

            const auto entries = scoped.cache->listEntries();
            const ClipCache::Entry* target = nullptr;

            for (const auto& entry : entries)
                if (entry.prompt == "delete me")
                    target = &entry;

            expect (target != nullptr, "could not find the run to delete");
            expect (scoped.cache->deleteEntry (*target), "delete reported failure");

            expect (! doomed.isDirectory(), "the directory is still on disk");
            expectEquals (scoped.cache->listEntries().size(), 1, "still listed after deletion");
            expectEquals (scoped.cache->listEntries().getReference (0).prompt, juce::String ("keep me"));
            expect (scoped.cache->getTotalSizeInBytes() < sizeBefore, "the size did not go down");
        }

        beginTest ("delete refuses a directory outside the cache");
        {
            // A stale entry held across a path change must not become an arbitrary
            // recursive delete of somewhere else on disk.
            ScopedCache scoped;

            auto outside = scoped.root.getChildFile ("not-the-cache");
            outside.createDirectory();
            outside.getChildFile ("precious.txt").replaceWithText ("do not delete me");

            ClipCache::Entry forged;
            forged.directory = outside;
            forged.clips.add (outside.getChildFile ("precious.txt"));

            expect (! scoped.cache->deleteEntry (forged), "deleted a directory outside the cache");
            expect (outside.isDirectory(), "the outside directory was removed");
            expect (outside.getChildFile ("precious.txt").existsAsFile(), "the file was destroyed");
        }

        beginTest ("pointing the cache at a folder of the user's own audio cannot delete it");
        {
            // The scenario that matters: the cache root is a path the user types. Aim
            // it at a music library and every album folder is a child of it, so
            // containment alone would have let 'Clear cache' recursively delete them.
            ScopedCache scoped;

            auto library = scoped.root.getChildFile ("Music");
            library.createDirectory();

            auto album = library.getChildFile ("Some Album");
            album.createDirectory();
            ScopedCache::writeWav (album.getChildFile ("track-1.wav"));
            album.getChildFile ("cover.jpg").replaceWithText ("not really a jpg");

            scoped.cache->setDirectory (library);

            // It lists — browsing an arbitrary folder read-only is harmless.
            const auto entries = scoped.cache->listEntries();
            expectEquals (entries.size(), 1);
            expect (! entries.getReference (0).createdByPlugin,
                    "someone else's folder was marked as ours");

            // But it must not be deletable.
            expect (! scoped.cache->deleteEntry (entries.getReference (0)),
                    "deleted a folder this plugin did not create");
            expect (album.isDirectory(), "the user's album was removed");
            expect (album.getChildFile ("track-1.wav").existsAsFile(), "the user's audio was destroyed");

            expectEquals (scoped.cache->clearAll(), 0, "Clear cache removed the user's own folders");
            expect (album.isDirectory(), "Clear cache destroyed the user's album");
        }

        beginTest ("run directories this plugin created are recognised");
        {
            // Including the collision-suffixed shape a same-second restart produces.
            expect (ClipCache::looksLikeARunDirectory (juce::File ("/tmp/20260730-112604-run1-2")));

            expect (ClipCache::looksLikeARunDirectory (juce::File ("/tmp/20260730-112604-run1")));
            expect (ClipCache::looksLikeARunDirectory (juce::File ("/tmp/run-1")),
                    "the pre-timestamp shape from US-23.3 is no longer recognised");

            expect (! ClipCache::looksLikeARunDirectory (juce::File ("/tmp/Some Album")));
            expect (! ClipCache::looksLikeARunDirectory (juce::File ("/tmp/run-nope")));
            expect (! ClipCache::looksLikeARunDirectory (juce::File ("/tmp/notadate-112604-run1")));
        }

        beginTest ("clearing removes every run");
        {
            ScopedCache scoped;
            scoped.makeRun ("one", 1, "a", 10.0);
            scoped.makeRun ("two", 2, "b", 10.0);
            scoped.makeRun ("three", 1, "c", 10.0);

            expectEquals (scoped.cache->clearAll(), 3);
            expectEquals (scoped.cache->listEntries().size(), 0);
            expectEquals ((int) scoped.cache->getTotalSizeInBytes(), 0);
            expect (scoped.cacheDir.isDirectory(), "clearing removed the cache folder itself");
        }

        beginTest ("an unusable cache path is reported rather than silently empty");
        {
            ScopedCache scoped;

            juce::String reason;
            expect (! scoped.cache->hasProblem (reason), "a good path reported a problem: " + reason);

            // Point it at a file.
            auto asFile = scoped.root.getChildFile ("a-file.txt");
            asFile.replaceWithText ("not a directory");
            scoped.cache->setDirectory (asFile);

            expect (scoped.cache->hasProblem (reason), "a file used as a cache path looked fine");
            expect (reason.isNotEmpty());
            expectEquals (scoped.cache->listEntries().size(), 0);
        }

        beginTest ("metadata round-trips through the sidecar exactly");
        {
            ScopedCache scoped;
            auto run = scoped.cacheDir.getChildFile ("round-trip");
            run.createDirectory();
            ScopedCache::writeWav (run.getChildFile ("clip-1.wav"));

            const juce::String prompt { "a prompt with \"quotes\", a \\ backslash and a newline\nsecond line" };
            expect (ClipCache::writeMetadata (run, prompt, "model-x", 123.5));

            const auto entry = ClipCache::readEntry (run);
            expect (entry.hasMetadata);
            expectEquals (entry.prompt, prompt, "the prompt was mangled by JSON encoding");
            expectEquals (entry.model, juce::String ("model-x"));
            expectWithinAbsoluteError (entry.durationSeconds, 123.5, 0.001);
        }
    }
};

static ClipCacheTests clipCacheTests;

} // namespace acemusic
