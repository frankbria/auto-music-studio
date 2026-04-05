## Dependency Graph

```
LAYER 1: CLI FOUNDATION (sequential)
S1 → S2 → S3 → S4 → S5 → S6 → S7

LAYER 2: PLATFORM API (sequential, depends on Layer 1)
S7 → S8 → S9 → S10 → S11 → S12 → S13 → S14

LAYER 3: WEB UI (sequential, depends on Layer 2)
S14 → S15 → S16 → S17 → S18 → S19 → S20 → S21

LAYER 4: ADVANCED INTEGRATIONS (partially parallel, depends on Layer 3)
S21 → S22 (Video Gen)          ─────────────────────────────────┐
S21 → S23 → S24 (VST3 Core → Advanced)                         │
S21 → S25 (Custom Voice Models)                                 ├→ S28 (Polish)
S21 → S26 → S27 (Credits → Moderation) ────────────────────────┘

CRITICAL PATH:
S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10 → S11 → S12 → S13 → S14
→ S15 → S16 → S17 → S18 → S19 → S20 → S21 → S26 → S27 → S28

PARALLEL OPPORTUNITIES (Layer 4):
┌──────────────────────────────────────────────────────────────────────┐
│  After Stage 21, the following can run in parallel:                  │
│                                                                      │
│  Track A: S22 (Video Gen)              ┐                             │
│  Track B: S23 → S24 (VST3)            ├─ All independent            │
│  Track C: S25 (Voice Models)           │                             │
│  Track D: S26 → S27 (Credits → Mod.)  ┘                             │
│                                                                      │
│  Stage 28 (Polish) depends on ALL of the above completing.           │
│                                                                      │
│  CROSS-LAYER parallelism:                                            │
│  - S23 (VST3 Core) can start during Layer 3 if S14 (Export API)     │
│    is complete (plugin talks to API, not web UI).                    │
│  - S25 (Voice Models) backend can start during Layer 2 if S9        │
│    (Generation API) is complete.                                     │
│  - S22 (Video Gen) backend can start during Layer 2 if S9 is        │
│    complete (needs generation API for song access).                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Appendix: Spec Section Cross-Reference

This table maps every spec section to the development stage(s) and user stories that implement it. Use this to verify complete specification coverage.

| Spec Section | Title | Stage(s) | Story IDs |
|---|---|---|---|
| §1 | Application Shell & Navigation | 15 | US-15.1, US-15.2, US-15.3 |
| §2 | Authentication & Account | 8, 15 | US-8.1, US-8.2, US-15.1 |
| §3 | Song Creation — Simple Mode | 2, 3, 9, 16 | US-2.3, US-3.1, US-9.1, US-16.1 |
| §4 | Song Creation — Advanced Mode | 3, 9, 16 | US-3.1, US-3.2, US-3.3, US-9.1, US-16.2 |
| §5 | Song Creation — Sounds Mode | 3, 9, 16 | US-3.5, US-9.1, US-16.3 |
| §6 | Audio Input Sources at Creation Time | 4, 10, 16 | US-4.4, US-10.1, US-16.4 |
| §7 | Generation Controls & Parameters | 3, 9, 16 | US-3.2, US-3.3, US-9.1, US-16.1 |
| §8 | Workspace & Clip Library Panel | 4, 9, 16 | US-4.1, US-4.2, US-9.2, US-16.5 |
| §9 | Clip Card — Actions & States | 4, 16 | US-4.2, US-16.5 |
| §10 | Remix & Edit Workflows | 6, 10, 17 | US-6.3, US-10.1, US-17.1 |
| §11 | Extend Workflow | 6, 10, 17 | US-6.1, US-10.2, US-17.2 |
| §12 | Cover Workflow | 6, 10, 17 | US-6.2, US-10.3, US-17.3 |
| §13 | Mashup Workflow | 6, 10, 17 | US-6.4, US-10.4, US-17.4 |
| §14 | Sample from Song (Beta) | 6, 10, 17 | US-6.5, US-10.5, US-17.5 |
| §15 | Replace Section | 6, 10, 17 | US-6.6, US-10.6, US-17.6 |
| §16 | Crop | 5, 10, 17 | US-5.1, US-10.7, US-17.7 |
| §17 | Adjust Speed | 5, 10, 17 | US-5.2, US-10.8, US-17.8 |
| §18 | Add Vocal | 6, 10, 17 | US-6.6, US-10.9, US-17.9 |
| §19 | Remaster | 5, 10, 17 | US-5.5, US-10.10, US-17.10 |
| §20 | Similar Songs Radio | 20 | US-20.3 |
| §21 | Get Full Song | 6, 10, 17 | US-6.7, US-10.11, US-17.11 |
| §22 | Open in Editor (Pro) | 19 | US-19.1 |
| §23 | Song Detail Page | 20 | US-20.1 |
| §24 | Studio — Multi-Track DAW | 19 | US-19.1, US-19.2, US-19.3, US-19.4 |
| §25 | Custom Voice Models | 25 | US-25.1, US-25.2, US-25.3, US-25.4 |
| §26 | Short-Form Audio/Video Feed | 20 | US-20.2 |
| §27 | Library (/me) | 20 | US-20.4 |
| §28 | Explore / Discovery | 20 | US-20.5 |
| §29 | Search | 20 | US-20.6 |
| §30 | Playlists | 20 | US-20.7 |
| §31 | Notifications | 20 | US-20.8 |
| §32 | Profile Page | 20 | US-20.9 |
| §33 | Publish & Visibility Controls | 20 | US-20.10 |
| §34 | Download & Export | 7, 14, 21 | US-7.1, US-7.2, US-14.1, US-21.1 |
| §35 | Cover Art Generation | 21 | US-21.2 |
| §36 | Stems & MIDI Extraction | 5, 14, 18 | US-5.3, US-5.4, US-14.2, US-18.1 |
| §37 | AI Engine — ACE-Step-1.5 | 2, 8, 11 | US-2.2, US-2.3, US-8.3, US-11.1 |
| §38 | Model Configuration & Selection | 3, 9 | US-3.4, US-9.3 |
| §39 | LoRA Training & Personalization | 25 | US-25.1, US-25.2 |
| §40 | Music Video Generator | 22 | US-22.1, US-22.2, US-22.3, US-22.4 |
| §41 | Automated Mastering Pipeline | 12, 21 | US-12.1, US-12.2, US-21.3 |
| §42 | Distribution & Release Management | 13, 21 | US-13.1, US-13.2, US-21.4 |
| §43 | DAW Export — Audio & MIDI | 7, 14 | US-7.2, US-7.3, US-7.4, US-14.1, US-14.2 |
| §44.1–44.3 | VST3 Plugin — Core (Overview, Stack, UI) | 23 | US-23.1, US-23.2, US-23.3, US-23.4, US-23.5 |
| §44.4–44.5 | VST3 Plugin — Advanced (DAW Integration, Modes) | 24 | US-24.1, US-24.2, US-24.3, US-24.4, US-24.5 |
| §44.6 | VST3 Plugin — File Management | 23 | US-23.5 |
| §44.7 | VST3 Plugin — System Requirements | 23 | US-23.1 |
| §45 | Credits & Subscription System | 26 | US-26.1, US-26.2, US-26.3, US-26.4, US-26.5 |
| §46 | Playback System (Global Player) | 15, 18 | US-15.4, US-18.2 |
| §47 | Content Moderation & Reporting | 27 | US-27.1, US-27.2, US-27.3, US-27.4 |
| §48 | Experimental Features | 28 | US-28.5 |
| §49 | Full UX Lifecycle Summary | — | Cross-cutting; validated by end-to-end acceptance tests across all stages |

**Coverage Notes:**
- All 49 spec sections are mapped to at least one development stage.
- §49 (Full UX Lifecycle Summary) is a cross-cutting description of the platform workflow rather than a discrete feature. It is validated implicitly by the integration of all stages.
- Story IDs for Layers 2–3 (Stages 8–21) reference the planned story numbering convention. Exact IDs will be confirmed when those layers are written.
- Some spec sections span multiple layers (e.g., §34 Download & Export appears in CLI, API, and UI layers) reflecting the "build outward from a runnable core" philosophy.
