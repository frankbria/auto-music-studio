#include "ConnectionSettings.h"

#if JUCE_LINUX || JUCE_MAC || JUCE_BSD
 #include <sys/stat.h>
#endif

namespace acemusic
{

namespace keys
{
    static constexpr const char* serverUrl = "serverUrl";
    static constexpr const char* apiKey    = "apiKey";
    static constexpr const char* modelId   = "modelId";
}

bool ConnectionSettings::operator== (const ConnectionSettings& other) const
{
    return serverUrl == other.serverUrl
        && apiKey    == other.apiKey
        && modelId   == other.modelId;
}

ConnectionSettings ConnectionSettings::readFrom (juce::PropertiesFile& properties)
{
    ConnectionSettings settings;

    // A stored-but-blank URL would leave the plugin unable to reach anything, so
    // treat it the same as absent.
    const auto storedUrl = properties.getValue (keys::serverUrl).trim();
    settings.serverUrl = storedUrl.isNotEmpty() ? storedUrl : juce::String (defaultServerUrl);

    settings.apiKey  = properties.getValue (keys::apiKey);
    settings.modelId = properties.getValue (keys::modelId);

    return settings;
}

void ConnectionSettings::writeTo (juce::PropertiesFile& properties) const
{
    properties.setValue (keys::serverUrl, serverUrl.trim());
    properties.setValue (keys::apiKey, apiKey);
    properties.setValue (keys::modelId, modelId);
    properties.saveIfNeeded();

    restrictPermissions (properties.getFile());
}

std::unique_ptr<juce::PropertiesFile> ConnectionSettings::createPropertiesFile()
{
    juce::PropertiesFile::Options options;
    options.applicationName     = "AceMusicStudio";
    options.filenameSuffix      = ".settings";
    options.folderName          = "AutoMusicStudio";
    options.osxLibrarySubFolder = "Application Support";

    return std::make_unique<juce::PropertiesFile> (options);
}

void ConnectionSettings::restrictPermissions (const juce::File& file)
{
   #if JUCE_LINUX || JUCE_MAC || JUCE_BSD
    if (file.existsAsFile())
        ::chmod (file.getFullPathName().toRawUTF8(), S_IRUSR | S_IWUSR);
   #else
    // Windows: the file lives under the per-user AppData tree, whose inherited ACL
    // already limits it to this user. Nothing useful to add without pulling in the
    // Win32 security APIs.
    juce::ignoreUnused (file);
   #endif
}

} // namespace acemusic
