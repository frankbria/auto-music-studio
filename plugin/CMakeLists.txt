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

# ---------------------------------------------------------------------------
# HTTPS (US-24.5)
#
# Until US-24.5 the plugin only talked to a local ACE-Step server over plain HTTP
# on localhost, so curl was switched off to avoid a Linux dev-package
# requirement. The platform API is a remote HTTPS host, so TLS is now needed.
#
# Only Linux needs curl for it: macOS goes through NSURLSession and Windows
# through WinHTTP, both of which do TLS natively. So rather than a hard
# requirement that breaks every Linux build without libcurl4-openssl-dev
# installed, curl is *detected*. Without it the plugin still builds and every
# local feature works; only the platform panel is unavailable, and it says so
# rather than failing an https:// request with a confusing socket error.
# ---------------------------------------------------------------------------
if(UNIX AND NOT APPLE)
    find_package(CURL QUIET)

    # CURL_FOUND alone is not enough: with only the runtime libcurl.so present it
    # reports success and points CURL_INCLUDE_DIR at a directory with no curl/
    # in it, and the build then fails on a missing curl.h. Observed on this very
    # machine before libcurl4-openssl-dev was installed, so the header is checked
    # for directly.
    set(ACEMUSIC_JUCE_CURL 0)

    if(CURL_FOUND)
        find_path(ACEMUSIC_CURL_HEADER curl/curl.h HINTS ${CURL_INCLUDE_DIRS} ${CURL_INCLUDE_DIR})

        if(ACEMUSIC_CURL_HEADER)
            set(ACEMUSIC_JUCE_CURL 1)
        endif()
    endif()

    if(NOT ACEMUSIC_JUCE_CURL)
        message(WARNING
            "libcurl development headers not found: building without HTTPS. "
            "The platform panel (US-24.5) will be unavailable and will say so. "
            "Install libcurl4-openssl-dev to enable it.")
    endif()
else()
    # macOS (NSURLSession) and Windows (WinHTTP) do TLS without curl.
    set(ACEMUSIC_JUCE_CURL 0)
endif()

# Whether this build can reach an https:// URL at all. Everything but a
# curl-less Linux can.
if(ACEMUSIC_JUCE_CURL OR NOT UNIX OR APPLE)
    set(ACEMUSIC_TLS 1)
else()
    set(ACEMUSIC_TLS 0)
endif()

set(ACEMUSIC_JUCE_DEFS
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=${ACEMUSIC_JUCE_CURL}
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0
    # Checked by the platform panel, so a curl-less Linux build explains itself
    # instead of failing an https:// request with a socket error.
    ACEMUSIC_HAS_TLS=${ACEMUSIC_TLS})

set(ACEMUSIC_SOURCES
    source/AceStepClient.cpp
    source/BackgroundTaskQueue.cpp
    source/ClipCache.cpp
    source/AudioIo.cpp
    source/ClipPlayer.cpp
    source/ConnectionManager.cpp
    source/ConnectionPanel.cpp
    source/ConnectionSettings.cpp
    source/GenerationManager.cpp
    source/GenerationPanel.cpp
    source/GenerationRequest.cpp
    source/HostSync.cpp
    source/HttpSupport.cpp
    source/LegoStack.cpp
    source/MidiCapture.cpp
    source/PlatformClient.cpp
    source/PluginProcessor.cpp
    source/PluginEditor.cpp
    source/ResultsPanel.cpp
    source/SidechainCapture.cpp
    source/TimeStretch.cpp)

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
    NEEDS_MIDI_INPUT            TRUE
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
        juce::juce_data_structures
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
    tests/AceStepClientTests.cpp
    tests/BackgroundTaskQueueTests.cpp
    tests/CaptureTests.cpp
    tests/ClipCacheTests.cpp
    tests/ClipPlayerTests.cpp
    tests/ConnectionManagerTests.cpp
    tests/ConnectionPanelTests.cpp
    tests/ConnectionSettingsTests.cpp
    tests/GenerationClientTests.cpp
    tests/GenerationManagerTests.cpp
    tests/GenerationPanelTests.cpp
    tests/GenerationRequestTests.cpp
    tests/LegoStackTests.cpp
    tests/HostSyncTests.cpp
    tests/PlatformClientTests.cpp
    tests/PluginProcessorTests.cpp
    tests/ResultsPanelTests.cpp
    tests/TimeStretchTests.cpp)

target_include_directories(AceMusicPluginTests PRIVATE source tests)

target_compile_definitions(AceMusicPluginTests PRIVATE
    ${ACEMUSIC_JUCE_DEFS}
    ACEMUSIC_PLUGIN_VERSION="${PROJECT_VERSION}"
    JUCE_UNIT_TESTS=1
    # Lets the runner pump the message loop synchronously to observe
    # callOnMessageThread deliveries. Test target only.
    JUCE_MODAL_LOOPS_PERMITTED=1)

# No juce_recommended_lto_flags here, unlike the plugin: LTO roughly doubles the
# link time and the test binary is never shipped.
target_link_libraries(AceMusicPluginTests PRIVATE
    juce::juce_audio_utils
    juce::juce_data_structures
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)

# JUCE_USE_CURL=1 only tells JUCE to *call* curl; the library still has to be
# linked, on every target that pulls in juce_core.
if(ACEMUSIC_JUCE_CURL)
    target_link_libraries(AceMusicPlugin PRIVATE CURL::libcurl)
    target_link_libraries(AceMusicPluginTests PRIVATE CURL::libcurl)
endif()

add_test(NAME unit COMMAND AceMusicPluginTests)
