#include "ConnectionSettings.h"

#if JUCE_LINUX || JUCE_MAC || JUCE_BSD
 #include <sys/stat.h>
#endif

namespace acemusic
{

class ConnectionSettingsTests final : public juce::UnitTest
{
public:
    ConnectionSettingsTests()
        : juce::UnitTest ("ConnectionSettings", "acemusic")
    {
    }

    struct TempStore
    {
        TempStore()
        {
            directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                            .getChildFile ("acemusic-settings-"
                                           + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
            directory.createDirectory();

            juce::PropertiesFile::Options options;
            options.applicationName = "TestSettings";
            options.filenameSuffix  = ".settings";
            options.storageFormat   = juce::PropertiesFile::storeAsXML;

            file = directory.getChildFile ("TestSettings.settings");
            properties = std::make_unique<juce::PropertiesFile> (file, options);
        }

        ~TempStore()
        {
            properties.reset();
            directory.deleteRecursively();
        }

        juce::File directory, file;
        std::unique_ptr<juce::PropertiesFile> properties;
    };

    void runTest() override
    {
        beginTest ("defaults to the local ACE-Step address");
        {
            const ConnectionSettings settings;
            expectEquals (settings.serverUrl, juce::String ("http://localhost:8001"));
            expect (settings.apiKey.isEmpty());
            expect (settings.modelId.isEmpty());
        }

        beginTest ("round-trips through a properties file");
        {
            TempStore store;

            ConnectionSettings written;
            written.serverUrl = "http://10.0.0.7:8100";
            written.apiKey    = "k-12345";
            written.modelId   = "ace-step-1.5";
            written.writeTo (*store.properties);

            const auto read = ConnectionSettings::readFrom (*store.properties);

            expect (read == written, "settings did not survive the round-trip");
            expectEquals (read.serverUrl, written.serverUrl);
            expectEquals (read.apiKey, written.apiKey);
            expectEquals (read.modelId, written.modelId);
        }

        beginTest ("reading an empty store yields the defaults");
        {
            TempStore store;
            const auto read = ConnectionSettings::readFrom (*store.properties);
            expect (read == ConnectionSettings{}, "empty store did not produce defaults");
        }

        beginTest ("a whitespace-only stored URL falls back to the default");
        {
            TempStore store;
            store.properties->setValue ("serverUrl", "  \t ");

            const auto read = ConnectionSettings::readFrom (*store.properties);
            expectEquals (read.serverUrl, juce::String (ConnectionSettings::defaultServerUrl));
        }

        beginTest ("the URL is trimmed on write");
        {
            TempStore store;

            ConnectionSettings settings;
            settings.serverUrl = "  http://host:1234  ";
            settings.writeTo (*store.properties);

            expectEquals (ConnectionSettings::readFrom (*store.properties).serverUrl,
                          juce::String ("http://host:1234"));
        }

        beginTest ("equality distinguishes each field");
        {
            const ConnectionSettings base;

            auto differentUrl = base;   differentUrl.serverUrl = "http://other:1";
            auto differentKey = base;   differentKey.apiKey    = "k";
            auto differentModel = base; differentModel.modelId = "m";

            expect (base != differentUrl);
            expect (base != differentKey);
            expect (base != differentModel);
            expect (base == ConnectionSettings{});
        }

       #if JUCE_LINUX || JUCE_MAC || JUCE_BSD
        beginTest ("the settings file is owner-only, since it holds the API key");
        {
            TempStore store;

            ConnectionSettings settings;
            settings.apiKey = "secret";
            settings.writeTo (*store.properties);

            expect (store.file.existsAsFile(), "no settings file was written");

            struct stat info {};
            expect (::stat (store.file.getFullPathName().toRawUTF8(), &info) == 0, "could not stat the file");

            const auto mode = info.st_mode & 0777;
            expectEquals ((int) mode, 0600,
                          "settings file mode is " + juce::String::toHexString ((int) mode)
                              + " — the API key is readable by others");

            // The directory matters more than the file: JUCE writes through the
            // process umask, so the file is briefly 0644 on every save no matter what
            // we chmod afterwards. A 0700 parent closes that window.
            struct stat dirInfo {};
            expect (::stat (store.file.getParentDirectory().getFullPathName().toRawUTF8(), &dirInfo) == 0,
                    "could not stat the settings directory");

            const auto dirMode = dirInfo.st_mode & 0777;
            expectEquals ((int) dirMode, 0700,
                          "settings directory mode is " + juce::String::toHexString ((int) dirMode)
                              + " — others can traverse into it while the file is being rewritten");
        }
       #endif

        beginTest ("the real config file lives under the user's config dir and is not created by asking");
        {
            const auto properties = ConnectionSettings::createPropertiesFile();
            expect (properties != nullptr);

            const auto file = properties->getFile();
            const auto path = file.getFullPathName();

            expect (path.contains ("AutoMusicStudio"),
                    "config path does not include the vendor folder: " + path);
            expect (path.contains ("AceMusicStudio"),
                    "config path does not include the app name: " + path);

           #if JUCE_LINUX || JUCE_BSD
            // JUCE resolves folderName under $HOME on Linux, so a bare folder name
            // would litter the user's home directory with a visible dir.
            expectEquals (file.getFullPathName(),
                          juce::File::getSpecialLocation (juce::File::userHomeDirectory)
                              .getChildFile (".config/AutoMusicStudio/AceMusicStudio.settings")
                              .getFullPathName());
           #endif
        }
    }
};

static ConnectionSettingsTests connectionSettingsTests;

} // namespace acemusic
