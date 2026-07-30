#include "ClipCache.h"

namespace acemusic
{

namespace
{
    constexpr const char* metadataFileName = "meta.json";

    juce::int64 sizeOfDirectory (const juce::File& directory)
    {
        juce::int64 total = 0;

        for (const auto& item : juce::RangedDirectoryIterator (directory, true, "*",
                                                               juce::File::findFiles))
        {
            total += item.getFile().getSize();
        }

        return total;
    }
}

ClipCache::ClipCache (juce::PropertiesFile* settingsToUse)
    : settings (settingsToUse)
{
}

juce::File ClipCache::getDefaultDirectory()
{
   #if JUCE_LINUX || JUCE_BSD
    // Same reasoning as the settings file in US-23.2: a bare folder name resolves
    // under $HOME on Linux, which would litter the user's home with a visible
    // directory. Generated audio is regenerable, so it belongs in the cache tree.
    return juce::File::getSpecialLocation (juce::File::userHomeDirectory)
               .getChildFile (".cache/AutoMusicStudio/clips");
   #elif JUCE_MAC
    return juce::File::getSpecialLocation (juce::File::userHomeDirectory)
               .getChildFile ("Library/Caches/AutoMusicStudio/clips");
   #else
    return juce::File::getSpecialLocation (juce::File::tempDirectory)
               .getSiblingFile ("AutoMusicStudio").getChildFile ("clips");
   #endif
}

juce::File ClipCache::getDirectory() const
{
    if (settings != nullptr)
    {
        const auto configured = settings->getValue (cachePathKey).trim();

        if (configured.isNotEmpty())
            return juce::File (configured);
    }

    return getDefaultDirectory();
}

void ClipCache::setDirectory (const juce::File& directory)
{
    if (settings == nullptr)
        return;

    // An empty path means "back to the default" rather than "the filesystem root".
    settings->setValue (cachePathKey,
                        directory == juce::File() ? juce::String() : directory.getFullPathName());
    settings->saveIfNeeded();
}

bool ClipCache::hasProblem (juce::String& reason) const
{
    const auto directory = getDirectory();

    if (directory.existsAsFile())
    {
        reason = "The cache path is a file, not a folder";
        return true;
    }

    if (! directory.isDirectory())
    {
        // Not an error yet — it is created on the first generation. Only report it if
        // we cannot make it.
        const auto result = directory.createDirectory();

        if (result.failed())
        {
            reason = "Cannot create the cache folder: " + result.getErrorMessage().trim();
            return true;
        }
    }

    if (! directory.hasWriteAccess())
    {
        reason = "The cache folder is not writable";
        return true;
    }

    reason.clear();
    return false;
}

bool ClipCache::looksLikeARunDirectory (const juce::File& directory)
{
    const auto name = directory.getFileName();

    // Current shape: 20260730-112604-run1
    if (name.matchesWildcard ("????????-??????-run*", false)
        && name.substring (0, 8).containsOnly ("0123456789")
        && name.substring (9, 15).containsOnly ("0123456789"))
    {
        return true;
    }

    // US-23.3/23.4 shape, before run directories were timestamped: run-1
    return name.startsWith ("run-") && name.fromFirstOccurrenceOf ("-", false, false)
                                            .containsOnly ("0123456789");
}

ClipCache::Entry ClipCache::readEntry (const juce::File& runDirectory)
{
    Entry entry;
    entry.directory = runDirectory;
    entry.createdByPlugin = looksLikeARunDirectory (runDirectory);

    if (! runDirectory.isDirectory())
        return entry;

    for (const auto& item : juce::RangedDirectoryIterator (runDirectory, false, "*.wav",
                                                           juce::File::findFiles))
    {
        entry.clips.add (item.getFile());
    }

    if (entry.clips.isEmpty())
        return entry;   // nothing playable here; caller drops it

    // Stable order — the iterator makes no promises, and "clip 1" should be clip 1.
    entry.clips.sort();

    entry.sizeInBytes = sizeOfDirectory (runDirectory);

    // Fall back to the directory's own timestamp so an entry without a sidecar still
    // sorts sensibly instead of landing at the epoch.
    entry.created = runDirectory.getCreationTime();

    const auto metadata = runDirectory.getChildFile (metadataFileName);

    if (metadata.existsAsFile())
    {
        const auto parsed = juce::JSON::parse (metadata.loadFileAsString());

        if (auto* object = parsed.getDynamicObject())
        {
            entry.hasMetadata = true;
            entry.prompt = object->getProperty ("prompt").toString();
            entry.model  = object->getProperty ("model").toString();
            entry.durationSeconds = (double) object->getProperty ("durationSeconds");

            const auto createdMs = (juce::int64) object->getProperty ("createdAtMs");

            if (createdMs > 0)
                entry.created = juce::Time (createdMs);
        }
    }

    return entry;
}

bool ClipCache::writeMetadata (const juce::File& runDirectory,
                               const juce::String& prompt,
                               const juce::String& model,
                               double durationSeconds)
{
    if (! runDirectory.isDirectory())
        return false;

    auto* object = new juce::DynamicObject();
    object->setProperty ("prompt", prompt);
    object->setProperty ("model", model);
    object->setProperty ("durationSeconds", durationSeconds);
    object->setProperty ("createdAtMs", juce::Time::getCurrentTime().toMilliseconds());

    return runDirectory.getChildFile (metadataFileName)
               .replaceWithText (juce::JSON::toString (juce::var (object), true));
}

juce::Array<ClipCache::Entry> ClipCache::listEntries() const
{
    juce::Array<Entry> entries;

    const auto directory = getDirectory();

    if (! directory.isDirectory())
        return entries;

    for (const auto& item : juce::RangedDirectoryIterator (directory, false, "*",
                                                           juce::File::findDirectories))
    {
        auto entry = readEntry (item.getFile());

        if (entry.isValid())
            entries.add (std::move (entry));
    }

    // Newest first: that is the order a musician wants past generations in.
    std::sort (entries.begin(), entries.end(), [] (const Entry& a, const Entry& b)
    {
        return a.created > b.created;
    });

    return entries;
}

juce::int64 ClipCache::getTotalSizeInBytes() const
{
    const auto directory = getDirectory();
    return directory.isDirectory() ? sizeOfDirectory (directory) : 0;
}

juce::String ClipCache::getTotalSizeDescription() const
{
    return juce::File::descriptionOfSizeInBytes (getTotalSizeInBytes());
}

bool ClipCache::deleteEntry (const Entry& entry)
{
    if (! entry.directory.isDirectory())
        return false;

    // Inside the configured cache — stops a stale entry held across a path change
    // from becoming an arbitrary recursive delete.
    if (! entry.directory.isAChildOf (getDirectory()))
        return false;

    // AND recognisably ours. Containment alone is not protection, because the cache
    // root is a path the user types: aim it at ~/Music and every album folder is a
    // child of it. Only directories named the way this plugin names its runs get
    // deleted; anything else lists read-only.
    if (! entry.createdByPlugin)
        return false;

    return entry.directory.deleteRecursively();
}

int ClipCache::clearAll()
{
    auto removed = 0;

    for (const auto& entry : listEntries())
        if (deleteEntry (entry))
            ++removed;

    return removed;
}

} // namespace acemusic
