cmake_minimum_required(VERSION 3.22)

project(AceMusicPlugin VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# JUCE
#
# Fetched rather than vendored or submoduled: nothing to keep in sync, and a
# shallow clone of a pinned tag is small enough to cache in CI.
#
# To build against a JUCE tree you already have, configure with
#   -DFETCHCONTENT_SOURCE_DIR_JUCE=/path/to/JUCE
# and no clone happens at all.
# ---------------------------------------------------------------------------
include(FetchContent)
FetchContent_Declare(JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG        8.0.9
    GIT_SHALLOW    ON)
FetchContent_MakeAvailable(JUCE)

# JUCE_USE_CURL=0: the plugin only ever talks to a local ACE-Step server over
# plain HTTP on localhost, which JUCE's built-in socket WebInputStream handles.
# Dropping curl removes a system dev-package requirement on Linux.
# ponytail: flip to 1 (and install libcurl4-openssl-dev in CI) if a later story
# needs HTTPS to a remote host.
set(ACEMUSIC_JUCE_DEFS
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

set(ACEMUSIC_SOURCES
    source/BackgroundTaskQueue.cpp
    source/PluginProcessor.cpp
    source/PluginEditor.cpp)

# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
set(ACEMUSIC_FORMATS VST3 Standalone)
if(APPLE)
    list(APPEND ACEMUSIC_FORMATS AU)
endif()

juce_add_plugin(AceMusicPlugin
    COMPANY_NAME                "Auto Music Studio"
    BUNDLE_ID                   com.automusicstudio.acemusic
    PLUGIN_MANUFACTURER_CODE    Amst
    PLUGIN_CODE                 Aces
    IS_SYNTH                    FALSE
    NEEDS_MIDI_INPUT            FALSE
    NEEDS_MIDI_OUTPUT           FALSE
    IS_MIDI_EFFECT              FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    COPY_PLUGIN_AFTER_BUILD     FALSE
    FORMATS                     ${ACEMUSIC_FORMATS}
    PRODUCT_NAME                "AceMusic Studio")

target_sources(AceMusicPlugin PRIVATE ${ACEMUSIC_SOURCES})
target_include_directories(AceMusicPlugin PUBLIC source)

target_compile_definitions(AceMusicPlugin PUBLIC
    ${ACEMUSIC_JUCE_DEFS}
    ACEMUSIC_PLUGIN_VERSION="${PROJECT_VERSION}")

target_link_libraries(AceMusicPlugin
    PRIVATE
        juce::juce_audio_utils
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags)

# ---------------------------------------------------------------------------
# Tests — juce::UnitTest suites in a console runner; `ctest` runs the binary.
#
# The plugin sources are compiled into the runner directly (rather than through
# a shared static lib) so the test target has no dependency on JUCE's plugin
# wrapper machinery.
# ---------------------------------------------------------------------------
enable_testing()

juce_add_console_app(AceMusicPluginTests PRODUCT_NAME "AceMusicPluginTests")

target_sources(AceMusicPluginTests PRIVATE
    ${ACEMUSIC_SOURCES}
    tests/TestMain.cpp
    tests/BackgroundTaskQueueTests.cpp
    tests/PluginProcessorTests.cpp)

target_include_directories(AceMusicPluginTests PRIVATE source)

target_compile_definitions(AceMusicPluginTests PRIVATE
    ${ACEMUSIC_JUCE_DEFS}
    ACEMUSIC_PLUGIN_VERSION="${PROJECT_VERSION}"
    JUCE_UNIT_TESTS=1
    # Lets the runner pump the message loop synchronously to observe
    # callOnMessageThread deliveries. Test target only.
    JUCE_MODAL_LOOPS_PERMITTED=1)

target_link_libraries(AceMusicPluginTests PRIVATE
    juce::juce_audio_utils
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)

add_test(NAME unit COMMAND AceMusicPluginTests)
