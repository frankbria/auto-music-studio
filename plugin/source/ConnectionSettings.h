#pragma once

#include <juce_data_structures/juce_data_structures.h>

#include <memory>

namespace acemusic
{

/**
    Where the plugin should look for an ACE-Step server, and which model to use.

    Persisted in a juce::PropertiesFile rather than the plugin's project state,
    because the requirement is to survive DAW *sessions* — project state would only
    come back inside the same project.
*/
struct ConnectionSettings
{
    juce::String serverUrl { defaultServerUrl };

    /** Optional; only needed for a secured server. Stored in plaintext — see
        restrictPermissions() and the note in plugin/README.md. */
    juce::String apiKey;

    /** Model name as reported by the server. Empty until one is chosen. */
    juce::String modelId;

    static constexpr const char* defaultServerUrl = "http://localhost:8001";

    bool operator== (const ConnectionSettings&) const;
    bool operator!= (const ConnectionSettings& other) const  { return ! operator== (other); }

    /** Reads settings, falling back to the defaults for anything missing. */
    static ConnectionSettings readFrom (juce::PropertiesFile& properties);

    /** Writes settings and flushes, then tightens file permissions. */
    void writeTo (juce::PropertiesFile& properties) const;

    /** The plugin's own config file: ~/.config/AutoMusicStudio/AceMusicStudio.settings
        on Linux, the platform equivalent elsewhere. */
    static std::unique_ptr<juce::PropertiesFile> createPropertiesFile();

    /** Makes `file` owner-read/write only. No-op on Windows, where the per-user
        AppData ACL already restricts it. */
    static void restrictPermissions (const juce::File& file);
};

} // namespace acemusic
