#include <juce_events/juce_events.h>

// Console runner for the plugin's juce::UnitTest suites. Suites register
// themselves via static instances in the *Tests.cpp files, so adding a suite
// means adding a source file to CMakeLists.txt — nothing to wire up here.
int main (int, char**)
{
    // Gives the tests a message thread, which BackgroundTaskQueue needs.
    const juce::ScopedJuceInitialiser_GUI juceInit;

    juce::UnitTestRunner runner;
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
