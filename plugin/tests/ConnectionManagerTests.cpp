#include "ConnectionManager.h"
#include "StubAceStepServer.h"

#include <juce_events/juce_events.h>

namespace acemusic
{

/** A PropertiesFile in a temp dir, so tests never touch the developer's real config. */
struct ScopedTempProperties
{
    ScopedTempProperties()
    {
        directory = juce::File::getSpecialLocation (juce::File::tempDirectory)
                        .getChildFile ("acemusic-tests-" + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
        directory.createDirectory();

        juce::PropertiesFile::Options options;
        options.applicationName = "TestSettings";
        options.filenameSuffix  = ".settings";
        options.storageFormat   = juce::PropertiesFile::storeAsXML;

        file = directory.getChildFile ("TestSettings.settings");
        properties = std::make_unique<juce::PropertiesFile> (file, options);
    }

    ~ScopedTempProperties()
    {
        properties.reset();
        directory.deleteRecursively();
    }

    juce::File directory, file;
    std::unique_ptr<juce::PropertiesFile> properties;
};

class ConnectionManagerTests final : public juce::UnitTest
{
public:
    ConnectionManagerTests()
        : juce::UnitTest ("ConnectionManager", "acemusic")
    {
    }

    /** Pumps the message loop until `predicate` holds or the timeout expires. Probe
        results arrive via callAsync, so tests have to let the loop run. */
    bool pumpUntil (std::function<bool()> predicate, int timeoutMs = 10000)
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

    void runTest() override
    {
        using Status = ConnectionManager::Status;

        beginTest ("starts disconnected with the default localhost URL");
        {
            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            expectEquals (manager.getSettings().serverUrl, juce::String (ConnectionSettings::defaultServerUrl));
            expect (manager.getStatus() == Status::Disconnected);
            expectEquals (manager.getModels().size(), 0);
            expect (! manager.isBusy());
        }

        beginTest ("AC: with the server running, a test reports Connected and lists its models");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0, "could not bind a stub server port");

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);

            manager.testConnection();
            expect (manager.getStatus() == Status::Connecting, "status did not go to Connecting immediately");

            expect (pumpUntil ([&] { return manager.getStatus() != Status::Connecting; }),
                    "probe never completed");

            expect (manager.getStatus() == Status::Connected,
                    "expected Connected, got \"" + manager.getStatusMessage() + "\"");
            expectEquals (manager.getModels().size(), 2);
            expectEquals (manager.getModels()[0], juce::String ("ace-step-1.5"));
            expectEquals (manager.getModels()[1], juce::String ("ace-step-mini"));

            // A model gets selected automatically so the dropdown is never blank on
            // a successful connection.
            expectEquals (manager.getSettings().modelId, juce::String ("ace-step-1.5"));
        }

        beginTest ("AC: with the server stopped, a test reports Error and 'Server unreachable'");
        {
            const auto closedPort = test::findClosedPort();
            expect (closedPort != 0);

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            ConnectionSettings settings;
            settings.serverUrl = "http://127.0.0.1:" + juce::String (closedPort);
            manager.setSettings (settings);

            manager.testConnection();

            expect (pumpUntil ([&] { return manager.getStatus() != Status::Connecting; }),
                    "probe never completed");

            expect (manager.getStatus() == Status::Error);
            expectEquals (manager.getStatusMessage(), juce::String ("Server unreachable"));
            expectEquals (manager.getModels().size(), 0);
        }

        beginTest ("AC: the server URL is saved and restored across sessions");
        {
            ScopedTempProperties store;
            const juce::String customUrl { "http://192.168.1.50:9100" };

            {
                // "Session" one: change the URL and let the manager go away.
                BackgroundTaskQueue queue;
                ConnectionManager manager (queue, store.properties.get());

                auto settings = manager.getSettings();
                settings.serverUrl = customUrl;
                settings.apiKey = "persisted-key";
                manager.setSettings (settings);
            }

            expect (store.file.existsAsFile(), "no settings file was written");

            {
                // "Session" two: a fresh manager over the same file.
                BackgroundTaskQueue queue;
                ConnectionManager manager (queue, store.properties.get());

                expectEquals (manager.getSettings().serverUrl, customUrl);
                expectEquals (manager.getSettings().apiKey, juce::String ("persisted-key"));
            }
        }

        beginTest ("a blank stored URL falls back to the default rather than leaving it unusable");
        {
            ScopedTempProperties store;
            store.properties->setValue ("serverUrl", "   ");
            store.properties->saveIfNeeded();

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, store.properties.get());

            expectEquals (manager.getSettings().serverUrl, juce::String (ConnectionSettings::defaultServerUrl));
        }

        beginTest ("changing the server clears a stale Connected status and model list");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);
            manager.testConnection();
            expect (pumpUntil ([&] { return manager.getStatus() == Status::Connected; }),
                    "did not reach Connected");

            // Point somewhere else — the green light and models belonged to the old server.
            settings.serverUrl = "http://127.0.0.1:1";
            manager.setSettings (settings);

            expect (manager.getStatus() == Status::Disconnected,
                    "kept a Connected status after the server changed");
            expectEquals (manager.getModels().size(), 0, "kept the previous server's model list");
        }

        beginTest ("choosing a model does not disturb the connection status");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);
            manager.testConnection();
            expect (pumpUntil ([&] { return manager.getStatus() == Status::Connected; }));

            manager.setSelectedModel ("ace-step-mini");

            expectEquals (manager.getSettings().modelId, juce::String ("ace-step-mini"));
            expect (manager.getStatus() == Status::Connected, "selecting a model dropped the connection");
            expectEquals (manager.getModels().size(), 2, "selecting a model cleared the model list");
        }

        beginTest ("a second test while one is in flight is ignored");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);

            manager.testConnection();
            manager.testConnection();
            manager.testConnection();

            expect (pumpUntil ([&] { return manager.getStatus() != Status::Connecting; }));
            expect (pumpUntil ([&] { return queue.getNumPending() == 0; }), "queue did not drain");

            expectEquals (server.getRequestCount(), 1, "fired more than one probe");
        }

        beginTest ("AC: auto-connect on load does not block, and lands Connected");
        {
            test::StubAceStepServer server;
            expect (server.start() != 0);

            ScopedTempProperties store;
            store.properties->setValue ("serverUrl", server.getBaseUrl());
            store.properties->saveIfNeeded();

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, store.properties.get());

            const auto before = juce::Time::getMillisecondCounter();
            manager.autoConnect();
            const auto elapsed = juce::Time::getMillisecondCounter() - before;

            // The host must not be held up: autoConnect only enqueues.
            expect (elapsed < 100, "autoConnect blocked for " + juce::String ((int) elapsed) + "ms");
            expect (manager.getStatus() == Status::Connecting, "did not enter Connecting");

            expect (pumpUntil ([&] { return manager.getStatus() != Status::Connecting; }),
                    "auto-connect never completed");
            expect (manager.getStatus() == Status::Connected,
                    "expected Connected, got \"" + manager.getStatusMessage() + "\"");
        }

        beginTest ("auto-connect with no URL configured does nothing");
        {
            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);

            auto settings = manager.getSettings();
            settings.serverUrl = "";
            manager.setSettings (settings);

            manager.autoConnect();

            expect (manager.getStatus() == Status::Disconnected, "probed despite having no URL");
            expectEquals (queue.getNumPending(), 0);
        }

        beginTest ("a probe outliving its manager is a no-op, not a crash");
        {
            // This is the WeakReference contract: the queue is declared first so it
            // outlives the manager, exactly as PluginProcessor orders them.
            test::StubAceStepServer server;
            expect (server.start() != 0);

            BackgroundTaskQueue queue;

            {
                ConnectionManager manager (queue, nullptr);

                ConnectionSettings settings;
                settings.serverUrl = server.getBaseUrl();
                manager.setSettings (settings);
                manager.testConnection();
                // manager dies here, with the probe possibly still in flight
            }

            expect (queue.waitForAll (10000), "queue did not drain after the manager went away");

            // Pump so any queued continuation actually runs — it must find a cleared
            // WeakReference and do nothing rather than touch freed memory.
            auto* mm = juce::MessageManager::getInstance();
            for (int i = 0; i < 20; ++i)
                mm->runDispatchLoopUntil (10);

            expect (true, "survived a probe completing after its manager was destroyed");
        }

        beginTest ("listeners are notified on every status transition");
        {
            struct CountingListener final : juce::ChangeListener
            {
                void changeListenerCallback (juce::ChangeBroadcaster*) override { ++count; }
                int count = 0;
            };

            test::StubAceStepServer server;
            expect (server.start() != 0);

            BackgroundTaskQueue queue;
            ConnectionManager manager (queue, nullptr);
            CountingListener listener;
            manager.addChangeListener (&listener);

            ConnectionSettings settings;
            settings.serverUrl = server.getBaseUrl();
            manager.setSettings (settings);
            manager.testConnection();

            expect (pumpUntil ([&] { return manager.getStatus() == Status::Connected; }));
            // ChangeBroadcaster coalesces, so assert "was told", not an exact count.
            expect (pumpUntil ([&] { return listener.count > 0; }), "listener was never notified");

            manager.removeChangeListener (&listener);
        }
    }
};

static ConnectionManagerTests connectionManagerTests;

} // namespace acemusic
