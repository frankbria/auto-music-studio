# Licensing — AceMusic Studio VST3 plugin

The plugin links the **JUCE Framework**, which is dual-licensed. This file records
which arm this repository uses, because the two arms impose opposite obligations and
the build configuration has to match the one we picked.

## The decision

**JUCE 8 End User Licence Agreement — Starter licence type. Not AGPLv3.**

Decided 2026-08-06 (issue #369). Pinned framework version: JUCE **8.0.9**
(`plugin/CMakeLists.txt`, `FetchContent` `GIT_TAG 8.0.9`), so the
[JUCE 8 EULA](https://juce.com/legal/juce-8-licence/) is the governing text.

| | Starter | Indie | Pro |
| --- | --- | --- | --- |
| Annual revenue or funding limit | **Up to $20,000** | Up to $300,000 | No limit |
| Perpetual price per user | **Free** | $800 | $3,500 |
| Monthly subscription per user | N/A | $40 | $175 |

Starter costs nothing and permits closed-source commercial distribution. We are at
$0 revenue, so we qualify today.

## What this means for the code

- **No source-offer obligation.** The AGPLv3 arm would require offering the plugin's
  complete corresponding source under AGPLv3, and would arguably reach how the plugin
  may talk to the rest of the platform. The commercial arm carries no such term, so
  `plugin/` may stay closed if we ever want it to.
- **`JUCE_DISPLAY_SPLASH_SCREEN=0` is permitted.** JUCE 8 **removed** the splash-screen
  requirement from the Starter tier — the JUCE 8 EULA contains no splash-screen clause
  at all, and JUCE's own release announcement calls this out as a JUCE 8 change. Under
  JUCE 5–7 this setting needed a paid tier; under JUCE 8 Starter it does not. The build
  as it stands is already consistent with this decision — no change was required.
- **Do not strip JUCE's own notices** (EULA 2.9): its copyright/trademark markings in
  the framework sources stay as they are. We do not vendor or patch JUCE — CMake fetches
  it at the pinned tag — so nothing here touches them.

## When this has to change

**Upgrade to Indie ($800 perpetual, or $40/month) before annual revenue reaches
$20,000.** Exceeding the limit is not a grace period: EULA 1.2.1 and the clause at
"If you exceed the Revenue or Funding Limit" require either buying the appropriate tier
**or immediately ceasing development and distribution**. Breach exposes us to back-fees
for the entire period plus audit costs of no less than £1,000 (EULA 3.6).

Two details worth knowing before that threshold is near:

- **How the $20,000 is counted depends on who holds the licence.** For an *individual*,
  it is only revenue arising from their use of the framework. For a *company*, it is the
  entity's and all its affiliates' total revenue **from all sources, whether connected to
  the framework or not, without offsets** (EULA 1.2.1). If this project is held by a
  company with any other income, that income counts.
- **Licence types cannot be mixed** (EULA 1.13). Products built under Starter may not be
  combined with products built under Indie or Pro, so the migration is a clean switch,
  not a per-product choice.

Also re-check this file if the pinned JUCE tag ever moves off 8.x — JUCE 9 ships a
different EULA, and none of the terms above carry over automatically.

## Not covered here

The **VST3 SDK is licensed separately by Steinberg** and is not part of the JUCE
licence. Building and distributing a VST3 binary needs its own agreement with
Steinberg (or the SDK's GPLv3 arm). Tracked separately — see issue #406.
