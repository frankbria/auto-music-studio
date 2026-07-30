#pragma once

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_data_structures/juce_data_structures.h>

namespace acemusic
{

/**
    The generated clips on disk, and what is known about them.

    Every generation writes its clips into `<cache>/run-N/` alongside a `meta.json`
    sidecar. The sidecar exists because the audio files carry none of what the browser
    has to show — the prompt, when it was made, how long it is — and re-deriving that
    from a WAV header and a timestamp would lose the prompt entirely.

    Reading the cache touches the disk, so call these from the message thread or a
    background worker, never from the audio callback.
*/
class ClipCache
{
public:
    /** One generation's worth of clips. */
    struct Entry
    {
        juce::File directory;
        juce::Array<juce::File> clips;

        juce::String prompt;
        juce::Time created;
        double durationSeconds = 0.0;
        juce::String model;

        /** Bytes on disk for this run. */
        juce::int64 sizeInBytes = 0;

        /** A run directory with clips in it but no readable sidecar still lists —
            losing a generation because its metadata went missing would be worse
            than showing it with a blank prompt. */
        bool hasMetadata = false;

        /** True only when this directory looks like one *this plugin* created.

            Deletion is gated on it. The cache root is a path the user types, so
            pointing it at, say, ~/Music would otherwise let "Clear cache"
            recursively delete their music folders — every one of them is a child of
            the configured directory, so containment alone is no protection. */
        bool createdByPlugin = false;

        bool isValid() const                                  { return ! clips.isEmpty(); }
    };

    /** @param settings  where the configured path is read from; null uses the default */
    explicit ClipCache (juce::PropertiesFile* settings);

    //==============================================================================
    /** The directory currently in use. */
    juce::File getDirectory() const;

    /** Where clips go when nothing is configured.

        Deliberately the platform *cache* location rather than the
        `~/ACEStepPlugin/cache/` the issue suggests: JUCE resolves a bare folder name
        under $HOME on Linux, so that would drop a visible directory into the user's
        home — the same thing fixed for the settings file in US-23.2. */
    static juce::File getDefaultDirectory();

    /** Points the cache somewhere else. Existing clips are left where they are;
        nothing is moved or deleted. Empty resets to the default. */
    void setDirectory (const juce::File& directory);

    /** True when the configured path is unusable (not a directory, or not writable),
        with `reason` set. The browser shows this rather than silently listing nothing. */
    bool hasProblem (juce::String& reason) const;

    //==============================================================================
    /** Every run in the cache, newest first. */
    juce::Array<Entry> listEntries() const;

    /** Total bytes across the whole cache. */
    juce::int64 getTotalSizeInBytes() const;

    /** Human-readable total, e.g. "12.4 MB". */
    juce::String getTotalSizeDescription() const;

    /** Deletes one run and everything in it.

        Refuses anything that is not inside the configured directory *and* does not
        look like a directory this plugin created. @returns false if not removed. */
    bool deleteEntry (const Entry&);

    /** True when `directory`'s name matches the shape this plugin gives its runs. */
    static bool looksLikeARunDirectory (const juce::File& directory);

    /** Deletes every run. @returns the number removed. */
    int clearAll();

    //==============================================================================
    /** Records what a generation produced, so the browser can describe it later.
        Called by GenerationManager once the clips are downloaded. */
    static bool writeMetadata (const juce::File& runDirectory,
                               const juce::String& prompt,
                               const juce::String& model,
                               double durationSeconds);

    /** Reads one run directory. `clips` is empty when there is nothing usable there. */
    static Entry readEntry (const juce::File& runDirectory);

    /** Settings key for the configured path. */
    static constexpr const char* cachePathKey = "cachePath";

private:
    juce::PropertiesFile* settings = nullptr;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ClipCache)
};

} // namespace acemusic
