# AceMusic Studio — VST3 plugin

JUCE-based plugin that brings ACE-Step generation into a DAW.

Progress:

| Story | State |
| --- | --- |
| US-23.1 — JUCE project, cross-platform build, off-audio-thread work queue | done |
| US-23.2 — Connection panel: server URL, API key, status, model list | done |
| US-23.3 — Generation panel | done |
| US-23.4 — Results panel and clip insertion | done |
| US-23.5 — Local cache and file management | done |
| US-24.1 — DAW tempo sync and tempo-matched insertion | done |
| US-24.2 — Selection-aware generation | done |
| US-24.3 — MIDI input and sidechain audio | done |

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
4. Set the project tempo to 120 and confirm the **BPM** field reads 120 and the
   indicator says `Sync: host 120 BPM`; change the project tempo and watch it
   follow. This is the one part of US-24.1 that no unit test can cover, because
   it needs a real host publishing a real tempo.
5. Set the cycle locators over bars 5–13 and confirm the panel reads
   `Selection: bars 5-13, 16.0s` with **Duration** at 16. Same reason: it needs a
   real host publishing a real loop range.

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

## Host sync

The plugin follows the DAW's tempo. Open it in a 120 BPM project and the **BPM**
field reads 120; drag the project tempo and the field follows. The **Sync**
indicator next to the parameter row says which of these is happening:

| Indicator | Meaning |
| --- | --- |
| `Sync: host 120 BPM` | BPM is following the host |
| `Sync: off (manual BPM)` | you typed a BPM; the host will not overwrite it |
| `Sync: no host tempo` | the host publishes no tempo — BPM stays on *Auto* |

**To take manual control**, type a BPM. **To hand it back**, clear the field —
empty is the panel's existing "Auto" state, so there is no extra button.

### Key is not synced, and cannot be

`juce::AudioPlayHead::PositionInfo` carries tempo, time signature, PPQ and the
transport flags — and **no key signature**. The only key-signature channel in
JUCE is [ARA](https://www.celemony.com/en/service1/about-celemony/technologies),
a separately licensed SDK that a handful of hosts implement. There is no way to
read the project key through VST3, AU or Standalone, so the **Key** field is
always manual. The indicator deliberately never claims otherwise.

### Selection

The plugin follows the host's **loop / cycle range** and sizes generation to it. Set
the cycle locators over bars 5–13 in a 120 BPM 4/4 project and the panel reads
`Selection: bars 5-13, 16.0s`, with the **Duration** field set to 16.

Duration follows the same rule as BPM: it tracks the host until you type your own
value, and clearing the field hands it back.

**It is the loop range, not an arbitrary time selection.** VST3 has no API for the
latter — `AudioPlayHead::PositionInfo::getLoopPoints()` is what exists, and JUCE fills
it from `Vst::ProcessContext::kCycleValid`. In Reaper the loop range is linked to the
time selection by default (Options → Loop points linked to time selection); in Cubase
and Logic these are the cycle markers. In a DAW where the two are not linked, moving
the time selection alone will not move the plugin's.

With no loop range set, the panel reads `Selection: none` and Duration keeps its
default of 60 — the Stage-23 behaviour, unchanged.

A loop range with no host tempo behind it shows the bars but no length, rather than
claiming `0.0s`.

### Where to drop it

The results panel tags each clip with the bar a drop should line up with —
`Clip 1  ->  120 BPM  @ bar 5`. The plugin cannot place the audio there itself: VST3
gives it no way to write the host's arrangement. This is the same resolution agreed on
[#318](https://github.com/frankbria/auto-music-studio/issues/318) for the playhead
readout — the plugin reports the position, and the drop stays yours.

### Tempo-matched insertion

If a clip was generated at a different BPM from the project, dragging it out
hands the host a **tempo-matched copy** rather than the original — a 118 BPM clip
dropped into a 120 BPM project arrives at 120.

The stretch is WSOLA (waveform-similarity overlap-add), not a resample.
Resampling would be less code, but it changes pitch with speed: 118→120 is a 1.7%
rate change and therefore a 29-cent detune, and audio that lands out of tune with
the project defeats the point of syncing to it in the first place.

Matched copies are written to a `tempo-match/` directory inside the run's cache
folder, built once per tempo on the background queue, and removed with the run.
They live in a subdirectory rather than beside the clip because the cache browser
lists `*.wav` per run non-recursively — as siblings they would be counted as
extra clips of that generation.

The clip's own tempo is the BPM that was **requested**, not one measured from the
returned audio. A generation that left BPM on *Auto* has no known tempo, so
nothing is stretched: guessing would be worse than leaving it alone. Detecting
the tempo of a finished clip is a separate story.

Everything reads the host transport through `HostSync`, which samples the play
head once in `processBlock` and publishes it. `getPlayHead()` is an audio-thread
API; calling it from a timer, as the results panel used to for its playhead
readout, is a data race.

## MIDI and sidechain input

Two more ways to seed a generation, beyond typing a prompt.

| Mode | Needs | Server task type |
| --- | --- | --- |
| Text to Music | nothing | *(server default)* |
| Cover | a sidechain capture | `cover` |
| Complete | a MIDI capture | `complete` |
| Repaint | a sidechain capture (+ the loop range) | `repaint` |

A mode is greyed out until its input has actually been captured, so the selector never
offers something that cannot be submitted.

### MIDI reaches the model as audio, not as MIDI

**ACE-Step has no MIDI input.** Its task types are `text2music`, `cover`, `repaint`,
`extract`, `lego`, `complete` and `mashup`, and `complete` — the one this feeds — takes
`src_audio_path`. There is not a single reference to MIDI anywhere in the ACE-Step
source.

So *Record MIDI* captures what you play, and the plugin **renders it to a plain tone**
which is submitted as the melodic reference. The rendering is a description of the
performance — pitch and rhythm — not an attempt to sound good. What conditions the model
is that audio, not your note data.

Nothing is synthesised on the audio thread: `processBlock` only pushes note events into
a lock-free FIFO, and the rendering happens on the message thread when you disarm.

If a take overruns the event buffer, the indicator says how many events were dropped
rather than reporting the take as clean.

### Sidechain

*Capture sidechain* records the plugin's sidechain input, for Cover and Repaint. The
sidechain bus is **disabled by default**, so a host with no sidechain send is unaffected
and existing sessions do not change shape; the toggle is unavailable until you route
something to it.

The capture buffer is allocated once, in `prepareToPlay`, and holds up to
`SidechainCapture::maxSeconds`. When it fills, recording stops and the indicator says so
— it does not wrap, because overwriting the start of a take would quietly hand the model
the wrong reference.

**Repaint's time range** comes from the host loop range (US-24.2), expressed as an
offset into the take rather than into the project. The transport position when the take
started is recorded for exactly this. If the loop range does not overlap the capture,
the range is omitted and the server decides.

Captures are written under `<cache>/captures/` and referenced by `src_audio_path`. That
is a **server-side** path, which works because the plugin targets a local ACE-Step;
a remote server would need an upload endpoint.

## Networking

The plugin is built with `JUCE_USE_CURL=0`. It talks to a *local* ACE-Step
server over plain HTTP on `localhost:8001`, which JUCE's built-in socket
`WebInputStream` handles, and dropping curl removes a system dev-package
requirement on Linux. If a later story needs HTTPS to a remote host, set
`JUCE_USE_CURL=1` in `CMakeLists.txt` and add `libcurl4-openssl-dev` to the
Linux dependencies above and to the CI workflow.

**All server traffic goes through `BackgroundTaskQueue`.** `processBlock` never
allocates, locks, or touches the network.

A probe running on a worker cannot interrupt its own blocking call, so its 2s
timeout is sized against the ~5s `juce::ThreadPool` allows in-flight work during
teardown.

**What that timeout bounds is not the same on every platform**, which matters if
you ever tune it:

| Platform | `withConnectionTimeout` means | Stalled-server worst case |
| --- | --- | --- |
| Linux/BSD (JUCE sockets, `JUCE_USE_CURL=0`) | connect timeout, re-applied as the poll timeout before each read | ~2x (≈4s) |
| macOS | `NSURLRequest.timeoutInterval` — inactivity across the whole request | ~1x (≈2s) |
| Windows | WinHTTP connect/send/receive timeouts | ~1x (≈2s) |

Even 4s fits the teardown budget; 3s (≈6s on Linux) would not have.

It is still not a hard bound on Linux, and this file shouldn't pretend otherwise.
The read path polls with the timeout but then calls `recv(…, MSG_WAITALL)`, which
blocks until the requested bytes arrive — a server that sends a partial body and
then neither sends nor closes can block a worker indefinitely, and closing the
plugin would abandon that thread. Bounding it properly needs a watchdog calling
`WebInputStream::cancel()`, which US-23.3 has to build anyway for long-running
generation requests (tracked on #317).
