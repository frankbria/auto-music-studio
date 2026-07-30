# AceMusic Studio — VST3 plugin

JUCE-based plugin that brings ACE-Step generation into a DAW. This is the
Stage 23 foundation (US-23.1): it builds, loads, shows a placeholder UI, and
provides the off-audio-thread work queue that the connection, generation, and
results panels will use.

| Format | Windows | macOS | Linux |
| --- | --- | --- | --- |
| VST3 | ✅ | ✅ | ✅ |
| AU | — | ✅ | — |
| Standalone | ✅ | ✅ | ✅ |

The Standalone build is a development convenience — it opens the same editor
without a host, which is the quickest way to look at UI changes.

## Requirements

- CMake 3.22+ and a C++17 compiler (MSVC 2022, Xcode 14+, or GCC 11+)
- Linux only:
  ```bash
  sudo apt-get install -y libasound2-dev libfreetype-dev libfontconfig1-dev \
    libx11-dev libxcomposite-dev libxcursor-dev libxext-dev \
    libxinerama-dev libxrandr-dev libxrender-dev libgl1-mesa-dev
  ```
  `libcurl` is deliberately **not** required — see "Networking" below.

JUCE itself is fetched by CMake (pinned to tag `8.0.9`); nothing to install.

## Build

```bash
cd plugin
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target AceMusicPlugin_VST3 --parallel
```

Artefacts land in `build/AceMusicPlugin_artefacts/Release/`. Other targets:
`AceMusicPlugin_Standalone`, `AceMusicPlugin_AU` (macOS), `AceMusicPluginTests`.

Already have a JUCE checkout? Skip the clone:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -DFETCHCONTENT_SOURCE_DIR_JUCE=/path/to/JUCE
```

## Test

```bash
cmake --build build --target AceMusicPluginTests --parallel
ctest --test-dir build -C Release --output-on-failure
```

The suites are `juce::UnitTest` classes registered under the `acemusic`
category, so the runner skips JUCE's own module tests. On a headless Linux box,
prefix with `xvfb-run -a`.

## Validate

[pluginval](https://github.com/Tracktion/pluginval) at strictness 10 is the
automated host check — it opens the plugin, instantiates and repaints the
editor, fuzzes parameters, and exercises the bus layouts.

```bash
pluginval --strictness-level 10 \
  --validate "build/AceMusicPlugin_artefacts/Release/VST3/AceMusic Studio.vst3"
```

CI (`.github/workflows/plugin.yml`) runs the build, the unit tests, the size
check, and pluginval on all three platforms.

### Manual DAW check

pluginval covers host behaviour, but it is not a DAW. Before a release, load
the VST3 in Reaper once and confirm the UI renders and audio passes through:

1. Copy `AceMusic Studio.vst3` to the VST3 folder
   (`~/.vst3` on Linux, `~/Library/Audio/Plug-Ins/VST3` on macOS,
   `%COMMONPROGRAMFILES%\VST3` on Windows).
2. Reaper → Options → Preferences → Plug-ins → VST → *Re-scan*.
3. Add it to a track with audio on it, open the UI, confirm the three panels
   render and the audio is unchanged.

## Connecting to ACE-Step

The plugin expects an ACE-Step server; the default is `http://localhost:8001`.
Set the URL (and an API key, if your server needs one) in the plugin's
**Connection** panel and press *Test Connection*. The indicator reads:

| Colour | Meaning |
| --- | --- |
| Grey | Not tried yet, or the server was changed since the last attempt |
| Amber | Probe in flight |
| Green | Server answered and reported at least one model |
| Red | Unreachable, rejected the API key, or returned nothing usable |

The probe is `GET /v1/stats` — ACE-Step has no `/health` endpoint. The model
dropdown is filled from `data.models[].name` in that response. A successful
connection auto-selects the first model if the saved one is no longer offered.

The plugin auto-connects once when the host loads it. That never blocks the DAW:
it queues the probe and updates the indicator when the result arrives.

### Settings file

Connection settings persist across DAW sessions in a plain config file, so they
follow you into new projects:

| Platform | Path |
| --- | --- |
| Linux | `~/.config/AutoMusicStudio/AceMusicStudio.settings` |
| macOS | `~/Library/Application Support/AutoMusicStudio/AceMusicStudio.settings` |
| Windows | `%APPDATA%\AutoMusicStudio\AceMusicStudio.settings` |

> **The API key is stored in that file in plaintext.** On Linux and macOS the
> file is chmod `0600` (owner read/write only); on Windows it inherits the
> per-user AppData ACL. This is the same posture as `~/.aws/credentials` or
> `~/.npmrc` — JUCE has no keychain abstraction, and a per-platform secure store
> is out of scope here. Delete the file to clear a stored key.

Settings live in this file rather than the plugin's project state on purpose:
project state would only come back inside the same DAW project, and the
requirement is to survive *sessions*.

## Networking

The plugin is built with `JUCE_USE_CURL=0`. It talks to a *local* ACE-Step
server over plain HTTP on `localhost:8001`, which JUCE's built-in socket
`WebInputStream` handles, and dropping curl removes a system dev-package
requirement on Linux. If a later story needs HTTPS to a remote host, set
`JUCE_USE_CURL=1` in `CMakeLists.txt` and add `libcurl4-openssl-dev` to the
Linux dependencies above and to the CI workflow.

**All server traffic goes through `BackgroundTaskQueue`.** `processBlock` never
allocates, locks, or touches the network.

A probe cannot be interrupted mid-connect from the thread it runs on, so its
connection timeout (3s) is deliberately set below the ~5s that
`juce::ThreadPool` allows in-flight work during teardown. The worst case is a
bounded delay when closing the plugin, not an abandoned thread.
