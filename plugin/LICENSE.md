# Licensing — AceMusic Studio VST3 plugin

The plugin links the **JUCE Framework**, which is dual-licensed, and through it the
**Steinberg VST3 SDK**. This file records which arm this repository uses for each,
because the arms impose different obligations and the build configuration has to match
the ones we picked.

> **Not legal advice.** This is a record of a decision and the clauses it rests on. The
> clause numbers are cited so the reasoning can be checked against the agreement itself
> rather than taken on trust — read the linked EULA before relying on any of it.

## The decision

**JUCE 8 End User Licence Agreement — Starter licence type. Not AGPLv3.**

Decided 2026-08-06 (issue #369). Pinned framework version: JUCE **8.0.14**
(`plugin/CMakeLists.txt`, `FetchContent` `GIT_TAG 8.0.14`; moved from 8.0.9 on
2026-09-17 for the VST3 SDK licence below — still JUCE 8, same EULA), so the
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

Two details worth knowing well before that threshold is reached:

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

## The VST3 SDK

**MIT licence, VST3 SDK 3.8.0, as bundled by JUCE 8.0.14. No agreement with Steinberg.**

Decided 2026-09-17 (issue #406). The VST3 SDK is Steinberg's, not JUCE's, and JUCE's
licence does not cover it at any tier. Until SDK 3.8 it was dual-licensed — a
proprietary agreement that had to be signed and returned to Steinberg, or GPLv3 — and
#406 was opened to pick one. Steinberg has since withdrawn both: from SDK **3.8** the
SDK is under the [MIT licence](https://steinbergmedia.github.io/vst3_dev_portal/pages/VST+3+Licensing/VST3+License.html),
"no need to sign any documents", no fee, no membership, and their FAQ confirms a
JUCE-based plug-in may be sold in binary form under it. We never signed the old
agreement, so the MIT SDK is the only arm available to us, and it is the better one.

**Which JUCE carries it matters.** JUCE 8.0.9 bundled SDK 3.7.4 under the old dual
licence; JUCE **8.0.11** is the first release that "updated the VST3 SDK to 3.8.0 (MIT
license)". That is why the pin moved to 8.0.14. Verify on any future bump:
`modules/juce_audio_processors_headless/format_types/VST3_SDK/LICENSE.txt` must be the
MIT text and `pluginterfaces/vst/vsttypes.h` must define `kVstVersionString` as
"VST 3.8.0" or later.

### What this means for the code

- **One obligation: the notice.** MIT requires Steinberg's copyright line and the licence
  text to accompany every copy of the SDK, including a binary that links it. The text is
  in `plugin/THIRD_PARTY_NOTICES.md`; any installer, download bundle, or store listing
  must ship that file alongside the plug-in. The same file carries the notices for the
  components JUCE compiles into the plug-in (audited in #499), and CI's package step
  stages it next to the VST3. There is no source-offer obligation.
- **"VST" is a Steinberg trademark.** Using the word, or the *VST Compatible* logo, is
  optional under MIT, but if used it must follow the
  [Steinberg VST usage guidelines](https://steinbergmedia.github.io/vst3_dev_portal/pages/VST+3+Licensing/Usage+guidelines.html).
  Our stance: we say "VST3 plugin" to name the format, carry the attribution line in the
  notices file, and do **not** use the logo. Adopting the logo commits us to showing it
  on every web page, document, and About box that mentions VST, which is a decision for
  whoever builds the product site. Never put "VST" in a company name, and never coin
  variants like "VSTi" — the guidelines prohibit both outright.
- **Leave `JUCE_ASIO` off.** From 8.0.11 JUCE also bundles the ASIO SDK, which is still
  under Steinberg's proprietary/GPLv3 dual licence. It is only compiled when
  `JUCE_ASIO=1`, which this build never sets. Enabling it would reopen exactly the
  question this section closes.
