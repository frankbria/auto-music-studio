#include <juce_events/juce_events.h>

#include "PlatformSession.h"

namespace
{
    /** Child-process mode for the cross-process refresh test (#516): one session, one call that needs a fresh
        access token, so the only request is the refresh. Exits 0 when the session ends up working. */
    int refreshSessionOnce (const juce::String& tokenFile, const juce::String& baseUrl)
    {
        acemusic::Platform::Session session { juce::File (tokenFile) };
        const auto result = session.run (baseUrl, [] (const juce::String& access)
        {
            acemusic::Platform::Result checked;
            checked.unauthorised = access != "access-live";
            checked.ok = ! checked.unauthorised;
            return checked;
        });

        if (! result.ok)
            std::cerr << result.errorMessage << "\n";

        return result.ok ? 0 : 1;
    }

    /** JUCE's default logs through Logger, which on Windows is OutputDebugString, so a
        crash there left no trace of the test that was running. Flushed per line for the
        same reason. */
    class StdoutTestRunner final : public juce::UnitTestRunner
    {
        void logMessage (const juce::String& message) override
        {
            std::cout << message << std::endl;
        }
    };
}

// Console runner for the plugin's juce::UnitTest suites. Suites register
// themselves via static instances in the *Tests.cpp files, so adding a suite
// means adding a source file to CMakeLists.txt — nothing to wire up here.
int main (int argc, char** argv)
{
    // Gives the tests a message thread, which BackgroundTaskQueue needs.
    const juce::ScopedJuceInitialiser_GUI juceInit;

    if (argc == 4 && juce::String (argv[1]) == "--refresh-session")
        return refreshSessionOnce (argv[2], argv[3]);

    juce::SystemStats::setApplicationCrashHandler ([] (void*)
    {
        std::cout << "CRASH backtrace:\n" << juce::SystemStats::getStackBacktrace() << std::endl;
    });

    StdoutTestRunner runner;
    runner.setAssertOnFailure (false);

    // Our suites only — runAllTests() would also run JUCE's own module tests,
    // which are slow and depend on audio/MIDI devices CI does not have.
    runner.runTestsInCategory ("acemusic");

    int failures = 0;

    for (int i = 0; i < runner.getNumResults(); ++i)
    {
        const auto* result = runner.getResult (i);
        failures += result->failures;

        if (result->failures > 0)
            std::cerr << "FAILED: " << result->unitTestName
                      << " / " << result->subcategoryName
                      << " (" << result->failures << " failure(s))\n";
    }

    if (failures == 0)
        std::cout << "All plugin unit tests passed.\n";

    return failures == 0 ? 0 : 1;
}
