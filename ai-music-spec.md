# AI Music Platform — Functional Specification
**Version:** 1.0 Draft (April 2026)
**Scope:** Full UX lifecycle — prompt-to-distribution pipeline covering song creation, editing, remixing, studio production, automated mastering, music video generation, distribution, and DAW integration via VST3 plugin
**AI Engine:** ACE-Step-1.5 (local deployment, forked at github.com/frankbria/ACE-Step-1.5)
**Note:** This specification describes a complete AI music production platform. Two primary workflows are supported: (1) an in-app workflow from prompt through mastering and distribution, and (2) a DAW-integrated workflow via audio/MIDI export and a VST3 plugin.

---

## Table of Contents

### Part I — In-App Creation & Editing
1. [Application Shell & Navigation](#1-application-shell--navigation)
2. [Authentication & Account](#2-authentication--account)
3. [Song Creation — Simple Mode](#3-song-creation--simple-mode)
4. [Song Creation — Advanced Mode](#4-song-creation--advanced-mode)
5. [Song Creation — Sounds Mode](#5-song-creation--sounds-mode)
6. [Audio Input Sources at Creation Time](#6-audio-input-sources-at-creation-time)
7. [Generation Controls & Parameters](#7-generation-controls--parameters)
8. [Workspace & Clip Library Panel](#8-workspace--clip-library-panel)
9. [Clip Card — Actions & States](#9-clip-card--actions--states)
10. [Remix & Edit Workflows](#10-remix--edit-workflows)
11. [Extend Workflow](#11-extend-workflow)
12. [Cover Workflow](#12-cover-workflow)
13. [Mashup Workflow](#13-mashup-workflow)
14. [Sample from Song (Beta)](#14-sample-from-song-beta)
15. [Replace Section](#15-replace-section)
16. [Crop](#16-crop)
17. [Adjust Speed](#17-adjust-speed)
18. [Add Vocal](#18-add-vocal)
19. [Remaster](#19-remaster)
20. [Similar Songs Radio](#20-similar-songs-radio)
21. [Get Full Song](#21-get-full-song)
22. [Open in Editor (Pro)](#22-open-in-editor-pro)
23. [Song Detail Page](#23-song-detail-page)
24. [Studio — Multi-Track DAW](#24-studio--multi-track-daw)
25. [Custom Voice Models](#25-custom-voice-models)

### Part II — Discovery & Social
26. [Short-Form Audio/Video Feed](#26-short-form-audiovideo-feed)
27. [Library (/me)](#27-library-me)
28. [Explore / Discovery](#28-explore--discovery)
29. [Search](#29-search)
30. [Playlists](#30-playlists)
31. [Notifications](#31-notifications)
32. [Profile Page](#32-profile-page)

### Part III — Publishing & Export
33. [Publish & Visibility Controls](#33-publish--visibility-controls)
34. [Download & Export](#34-download--export)
35. [Cover Art Generation](#35-cover-art-generation)
36. [Stems & MIDI Extraction](#36-stems--midi-extraction)

### Part IV — AI Engine & Model Integration
37. [AI Engine — ACE-Step-1.5](#37-ai-engine--ace-step-15) · [37.8 Cloud Backend: ElevenLabs](#378-cloud-backend-elevenlabs-fallback--alternative)
38. [Model Configuration & Selection](#38-model-configuration--selection)
39. [LoRA Training & Personalization](#39-lora-training--personalization)

### Part V — Music Video Creation
40. [Music Video Generator](#40-music-video-generator)

### Part VI — Mastering & Distribution Pipeline
41. [Automated Mastering Pipeline](#41-automated-mastering-pipeline)
42. [Distribution & Release Management](#42-distribution--release-management)

### Part VII — DAW Integration & VST3 Plugin
43. [DAW Export — Audio & MIDI](#43-daw-export--audio--midi)
44. [VST3 Plugin — DAW Bridge](#44-vst3-plugin--daw-bridge)

### Part VIII — Platform & Operations
45. [Credits & Subscription System](#45-credits--subscription-system)
46. [Playback System (Global Player)](#46-playback-system-global-player)
47. [Content Moderation & Reporting](#47-content-moderation--reporting)
48. [Experimental Features](#48-experimental-features)
49. [Full UX Lifecycle Summary](#49-full-ux-lifecycle-summary)

---

## Part I — In-App Creation & Editing

---

## 1. Application Shell & Navigation

### 1.1 Layout
The application uses a two-panel layout:
- **Left Sidebar (collapsed icon bar):** Primary navigation via icon buttons
- **Main Content Area:** Context-sensitive based on current route
- **Right Panel (contextual):** Song details, similar songs, or inspector panel
- **Bottom Playbar:** Persistent global audio player across all pages

### 1.2 Sidebar Navigation Icons
| Icon Position | Destination | Route |
|---|---|---|
| Home | Home / Feed | `/` |
| Compass | Explore / Discover | `/explore` |
| Music Note | Create | `/create` |
| Share/Network | Studio | `/studio` |
| Library | Library | `/me` |
| Search | Search | `/search` |
| Trending | Short-Form Feed | `/feed` |
| Bell | Notifications | `/notifications` |
| Upload/Export | Mastering & Distribution | `/release` |
| Plug | VST3 / DAW Integration | `/daw` |
| Flask (bottom) | Experimental Features | `/labs` |
| Circle (bottom) | Subscription / Account dialog | dialog |

### 1.3 Sidebar Expand
- A "Expand sidebar" button at the top toggles the sidebar between icon-only and full-label mode.

### 1.4 Profile Menu
- Avatar button at top of sidebar opens a dropdown: profile link, account settings, subscription, logout.

---

## 2. Authentication & Account

### 2.1 Login / Sign Up
- Authentication via OAuth/SSO identity providers (e.g., Google, Discord, Apple).
- Optionally support email/password registration.
- Login redirects the user to the Create page on success.

### 2.2 Profile Settings
- Display name
- Username handle (e.g., `@username`)
- Profile avatar (image upload)
- Bio / description text
- Preferred style tags (displayed on profile as pill badges, e.g., "cello," "orchestral")
- Profile is publicly accessible at `/@username`

### 2.3 Subscription Tiers
- **Free:** Limited credits per period, basic features
- **Pro:** Unlocks advanced features (lossless download, multi-track editor, stems/MIDI export, crop, replace section, add vocal, use as inspiration, priority generation queue, automated mastering, DAW export)
- **Credits system:** Credits are consumed per generation action; advanced features (e.g., custom voice model training, mastering jobs) may cost additional credits

---

## 3. Song Creation — Simple Mode

**Route:** `/create` → **Simple** tab

### 3.1 Overview
Simple mode accepts a **natural language song description** and handles all style/lyric decisions automatically. Designed for quick, low-configuration generation.

### 3.2 Input Fields
| Field | Description |
|---|---|
| **Song Description** textarea | Free-form natural language prompt describing the song (e.g., "A mellow folk metal song about the tree outside my window"). The AI interprets genre, mood, tempo, instrumentation, and lyrical themes. |
| **Instrumental toggle** | Boolean toggle to suppress vocals and generate an instrumental track. |
| **+ Audio button** | Attach an audio reference (see §6). |
| **+ Lyrics button** | Inject custom lyrics into the song (overrides AI lyric generation). |
| **Inspiration tags** | AI-suggested style tags appear as clickable pills below the description. The user can click a tag to add it to the generation context. Tags are shuffled/refreshed with a shuffle button. |

### 3.3 Create Button
- Disabled until at least one form field is populated.
- Triggers generation; produces **2 clips** per submission by default.
- Generated clips appear in the Workspace panel on the right.
- Each generation consumes credits.

---

## 4. Song Creation — Advanced Mode

**Route:** `/create` → **Advanced** tab

### 4.1 Overview
Advanced mode exposes discrete control over lyrics, style strings, and generation parameters. The user constructs the song manually rather than relying on natural language description.

### 4.2 Lyrics Panel
| Control | Description |
|---|---|
| **Lyrics textarea** | Full lyrics editor. Accepts freeform text. Placeholder: "Write some lyrics or leave blank for instrumental." Supports structured sections using tags (e.g., `[Verse]`, `[Chorus]`, `[Bridge]`, `[Outro]`). |
| **Vocal Language** | Dropdown selector for target vocal language (50+ languages supported). "Auto" detects language from lyrics text. |
| **Enhance lyrics input** | Secondary text field for AI transformation instructions (e.g., "make it sound happier," "add a pre-chorus"). The AI rewrites/augments the lyrics accordingly. |
| **Undo lyrics changes** | Reverts lyrics to previous state (disabled if no changes). |
| **Save lyrics prompt** | Saves current lyrics to a named preset (disabled if no content). |
| **Clear lyrics** | Empties the lyrics field (disabled if empty). |
| **Lyrics mode toggle** | Switches between **Manual** (user writes all lyrics) and **Auto** (AI generates lyrics from style context). |

### 4.3 Styles Panel
| Control | Description |
|---|---|
| **Styles textarea** | Comma-separated style descriptors (e.g., "dark electro, punchy percussion, brushed drums, hazy, prog dream pop"). These are the primary tonal/genre/instrument signals to the model. |
| **Personalized magic wand** | Applies the user's personalized style profile (based on their listening/creation history) to auto-populate or modify the styles field. |
| **Style tag pills** | Clickable suggestion pills appear below the textarea. Each pill adds its label to the styles string. Shuffle button randomizes the suggestions. |
| **Undo style changes** | Reverts style string to previous state. |
| **Save style preset** | Saves style string for reuse. |
| **Clear styles** | Empties the styles field. |

### 4.4 More Options (Expandable)
Collapsed by default; reveals additional generation parameters:

| Parameter | Type | Description |
|---|---|---|
| **Exclude Styles** | Text input | Styles/genres to explicitly avoid (e.g., "rock, jazz, funk, hip hop"). Acts as a negative style prompt. |
| **Vocal Gender** | Toggle: Male / Female | Specifies the preferred vocal gender for the generated performance. |
| **Lyrics Mode** | Select: Manual / Auto | Same as in the Lyrics panel. |
| **BPM** | Numeric input (60–180) or "Auto" | Sets the target tempo. "Auto" lets the AI choose based on style context. |
| **Key** | Selector: "Any" or specific musical key | Sets the tonal center (e.g., C major, A minor). |
| **Time Signature** | Selector: 4/4, 3/4, 6/8, 5/4, 7/8 | 4/4 is default and most reliable; experimental signatures are less stable. |
| **Duration** | Numeric input (seconds) or preset | Target length: 30–60s (short), 90–120s (recommended), 120–240s (full song). Longer durations may exhibit repetition. |
| **Weirdness** | Slider 0–100% (default 50%) | Controls how far the model deviates from conventional song structures and sounds. Higher values produce more experimental, unconventional output. |
| **Style Influence** | Slider 0–100% (default 50%) | Controls how strictly the model adheres to the provided style descriptors vs. exercising creative latitude. |
| **Song Title** | Text input (optional) | Sets the title of the generated clips. If blank, the system auto-names clips. |
| **Save to Workspace** | Dropdown selector | Chooses which workspace to save the generated clips to (e.g., "My Workspace" or any custom workspace). |
| **Seed** | Numeric input or "Random" | Fixed seed for reproducible output; "Random" (default) for variety. |

### 4.5 Model/Version Selector
A version badge button opens a dropdown of available generation models:
- **Create Custom Model (Beta)** — Premium credit cost — for training personalized voice/style models via LoRA
- **Latest Model (XL)** — Highest quality (4B DiT), supports custom voices and advanced features
- **Standard Model** — Balanced quality and speed (2B DiT)
- **Turbo Model** — Fast generation (8 inference steps), lower quality ceiling
- **Legacy Models** — Previous-generation models retained for compatibility

The user selects which model generates the output. Premium models may require an active Pro subscription.

---

## 5. Song Creation — Sounds Mode

**Route:** `/create` → **Sounds** tab

### 5.1 Overview
Sounds mode generates short audio samples rather than full songs — suitable for sound effects, loops, one-shots, and instrument parts.

### 5.2 Input Fields
| Field | Description |
|---|---|
| **Sound description** | Natural language description of the desired sound (e.g., "a deep punchy kick drum," "rain on leaves," "orchestral swell"). |
| **Type** | Selector: **One-Shot** (single-trigger, non-looping) or **Loop** (seamlessly loopable audio). |
| **BPM** | Numeric or "Auto" — sets the tempo of looped samples for DAW-compatibility. |
| **Key** | Selector: "Any" or specific musical key — sets the tonal center of melodic/harmonic sounds. |

### 5.3 Output
- Generates short audio clips (seconds long).
- Clips are stored in the same workspace as songs.
- Can be imported directly into Studio as track clips.
- Loop clips include tempo metadata for DAW import sync.

---

## 6. Audio Input Sources at Creation Time

At the top of the create form (both Simple and Advanced), three optional input modes are available:

### 6.1 Add Audio (Remix / Upload / Record)
A modal with three sub-modes:
- **Remix:** Select an existing clip from the user's workspace library or search public songs. The selected clip's audio is used as a structural/tonal reference for generation.
- **Upload:** Upload an audio file from the local filesystem. The system analyzes the uploaded audio and uses it as a style/tonal reference. Accepted formats: WAV, FLAC, MP3, OGG, AAC, AIFF.
- **Record:** Record audio directly in the browser using the microphone. The recording is used as the audio reference.

Sub-tabs visible in the Edit panel also include: **Remix**, **Inspo**, **Mashup**, **Sample**.

### 6.2 Add Voice
- Opens a modal to attach a **custom voice model** (trained LoRA persona) to the generation.
- The selected voice determines the vocal timbre and performance style of the output.

### 6.3 Add Inspiration (Inspo)
- Allows the user to reference a **playlist** as inspirational context.
- The AI analyzes the playlist's collective style and uses it to guide generation.

---

## 7. Generation Controls & Parameters

### 7.1 Create Button Behavior
- Greyed out / disabled until minimum required inputs are satisfied.
- On click: submits the full form to the AI backend (ACE-Step-1.5 REST API).
- Results (2 clips by default) appear in the Workspace panel as new cards, loading in real time with a generation progress indicator.
- If generation fails, an error state is shown with a retry option.
- Generation time estimate displayed based on selected model (Turbo: ~2–5s, Standard: ~10–30s, XL: ~30–60s on consumer GPU).

### 7.2 Clear All
- A "Clear all form inputs" button resets all fields on the create form to their defaults.

---

## 8. Workspace & Clip Library Panel

**Location:** Right side of the Create page

### 8.1 Header Controls
| Control | Description |
|---|---|
| **Workspaces breadcrumb** | Shows current workspace path (e.g., "Workspaces > My Workspace"). Clicking navigates to the Workspaces list. |
| **Search clips** | Text search filtering clips by title or metadata. |
| **Filters button** | Opens filter panel. Shows count of active filters (e.g., "Filters (3)"). |
| **Sort: Newest** | Sort dropdown — sort clips by Newest, Oldest, or other criteria. |
| **Liked** | Filter to show only clips the user has liked. |
| **Public** | Filter to show only published (public) clips. |
| **Uploads** | Filter to show only clips the user uploaded (vs. AI-generated). |
| **Pagination** | Previous/Next page buttons + current page number input. |

### 8.2 Clip Card (List View)
Each clip in the workspace panel is rendered as a row with:
- **Thumbnail** with duration overlay and play button
- **Title** (with inline edit pencil icon)
- **Version badge** (indicates which AI model generated the clip)
- **Metadata badge** (e.g., "Cover," "Upload," "Studio," "Extend 1," "Mastered")
- **Style description** (truncated)
- **Like / Dislike / Share** action buttons
- **Publish button** (toggles public visibility)
- **"Get Full Song" button** (visible on very short extend clips — triggers full-length assembly)
- **Remix/Edit button** (primary edit CTA with dropdown arrow)
- **More options (⋯) menu**

---

## 9. Clip Card — Actions & States

### 9.1 Inline Actions
| Action | Description |
|---|---|
| **Play** | Plays/pauses clip in the global player |
| **Like** | Marks clip as liked (heart icon); affects discovery/filtering |
| **Dislike** | Downvotes clip; affects recommendations |
| **Share** | Opens share modal with link and social options |
| **Publish** | Toggles public/private visibility |
| **Edit Title** | Inline rename of clip title |

### 9.2 More Options (⋯) Menu — Full Structure
- Remix/Edit ▶
- Open in Studio
- Open in Editor (Pro)
- Cover
- Extend
- Mashup
- Sample from Song (Beta)
- Use as Inspiration
- **Send to Mastering** ▶ (see §41)
- **Export to DAW** ▶ (see §43)
- **Create Music Video** (see §40)
- Download ▶ (MP3 / WAV / FLAC / Stems)
- Delete

---

## 10. Remix & Edit Workflows

### 10.1 Remix
- Select any clip (own or public) as a **source**.
- The source audio is analyzed for structure, key, tempo, and tonal character.
- User provides new style descriptors, lyrics, or parameter overrides.
- AI generates a new clip that reinterprets the source within the new style context.
- The remix retains structural DNA (melody contour, rhythm feel) while transforming genre/instrumentation.

### 10.2 Edit (Repaint Mode)
- Opens the clip in a waveform timeline view.
- User selects a **time range** within the clip.
- Provides new instructions (prompt/style/lyrics) for the selected region only.
- AI regenerates only the selected section, blending seamlessly with surrounding audio.
- Non-selected regions remain untouched.

---

## 11. Extend Workflow

### 11.1 Overview
Extends an existing clip by generating additional audio that continues the song naturally.

### 11.2 Controls
| Control | Description |
|---|---|
| **Extend from** | Select extension point: end of clip (default) or a specific timestamp. |
| **Extension duration** | Target additional length (30s, 60s, 90s, or custom). |
| **Style override** | Optional — change style for the extension (e.g., add a bridge or outro feel). |
| **Lyrics continuation** | Provide lyrics for the extended section, or let AI generate. |

### 11.3 Behavior
- Generates a new clip segment that begins where the source ends.
- Tempo, key, and timbre continuity is maintained.
- The result is a new clip containing the original + extension.
- Multiple extends can be chained to build a full-length song from a seed.

---

## 12. Cover Workflow

### 12.1 Overview
Generates a **cover version** of an existing song — same melodic structure, different style/arrangement/voice.

### 12.2 Controls
| Control | Description |
|---|---|
| **Source clip** | The clip to cover (own clip, uploaded audio, or public song). |
| **Target style** | New style descriptors (e.g., "jazz piano trio," "heavy metal," "lo-fi bedroom pop"). |
| **Voice selection** | Optional custom voice model for the cover vocal performance. |
| **Lyrics override** | Optional — change lyrics while preserving melody. |

### 12.3 Behavior
- Preserves the melodic contour and song structure of the source.
- Applies new instrumentation, tempo adjustments, and vocal style.
- Output is a full new clip.

---

## 13. Mashup Workflow

### 13.1 Overview
Combines elements from **two or more source clips** into a single new generation.

### 13.2 Controls
| Control | Description |
|---|---|
| **Source clips** | Select 2+ clips from workspace or search. |
| **Blend mode** | How sources combine: **Layered** (concurrent elements), **Sequential** (section-by-section), or **AI-Guided** (model decides). |
| **Style override** | Optional unifying style for the mashup. |

### 13.3 Behavior
- AI analyzes BPM, key, and structure of all sources.
- Tempo/key alignment is automatic where possible.
- Output is a single new clip blending the sources.

---

## 14. Sample from Song (Beta)

### 14.1 Overview
Extracts a short audio segment from an existing clip and uses it as a **loop or sample** in a new generation.

### 14.2 Controls
| Control | Description |
|---|---|
| **Source clip** | The song to sample from. |
| **Time range** | Start/end selection of the sample (waveform scrubber). |
| **Sample role** | How the sample is used: **Loop bed**, **Intro/Outro**, **Rhythmic element**, or **Melodic hook**. |
| **Generation prompt** | Additional style/lyric instructions for building a new song around the sample. |

### 14.3 Behavior
- The selected audio slice is extracted and embedded as a constraint in the generation.
- The AI builds a new composition that incorporates the sample organically.
- Attribution metadata links back to the source clip.

---

## 15. Replace Section

### 15.1 Overview
Regenerates a specific section of a clip while keeping the rest intact. Pro feature.

### 15.2 Controls
| Control | Description |
|---|---|
| **Section selection** | Waveform timeline with draggable start/end markers. |
| **Replacement instructions** | Prompt describing what the new section should sound like. |
| **Lock surrounding context** | Toggle — ensures the replacement blends seamlessly with adjacent audio. |

### 15.3 Behavior
- Only the selected time range is regenerated.
- Cross-fade/blending is applied at section boundaries.
- Original clip is preserved; a new clip version is created.

---

## 16. Crop

### 16.1 Overview
Trims a clip to a selected time range. Pro feature.

### 16.2 Controls
- Waveform timeline with draggable start/end crop markers.
- Snap-to-beat option for rhythmically precise crops.
- Fade-in/fade-out toggle (with configurable duration).

### 16.3 Behavior
- Creates a new clip containing only the cropped region.
- Original clip is preserved.

---

## 17. Adjust Speed

### 17.1 Overview
Changes the playback speed / tempo of a clip without altering pitch (time-stretch).

### 17.2 Controls
| Control | Description |
|---|---|
| **Speed multiplier** | Slider: 0.5x – 2.0x (default 1.0x). |
| **Preserve pitch** | Toggle (default on) — maintains original pitch while changing tempo. |
| **Target BPM** | Alternative input — specify exact BPM and let system calculate multiplier. |

---

## 18. Add Vocal

### 18.1 Overview
Adds a vocal track to an instrumental clip, or replaces existing vocals. Pro feature.

### 18.2 Controls
| Control | Description |
|---|---|
| **Source clip** | The instrumental (or existing song) to add vocals to. |
| **Lyrics** | Text lyrics for the vocal performance. |
| **Voice model** | Custom voice model or default AI voice. |
| **Vocal style** | Descriptors: "breathy," "powerful," "whispered," "raspy," etc. |

### 18.3 Behavior
- AI generates a vocal performance matching the clip's key, tempo, and structure.
- The vocal is layered onto the source audio.
- Output is a new clip with vocals integrated.

---

## 19. Remaster

### 19.1 Overview
AI-powered audio enhancement that improves the overall sonic quality of a clip.

### 19.2 Behavior
- One-click operation — no user configuration required.
- Applies dynamic range optimization, EQ balancing, stereo enhancement, and loudness normalization.
- Creates a new clip version marked as "Remastered."
- Does **not** replace the original.

### 19.3 Distinction from Mastering Pipeline
- Remaster is a quick, in-app enhancement (single-clip, AI-based).
- The Mastering Pipeline (§41) is a professional-grade export workflow using external mastering APIs (Dolby.io, LANDR, etc.) with configurable profiles and distribution-ready output.

---

## 20. Similar Songs Radio

### 20.1 Overview
Generates an auto-playing queue of clips similar to a selected seed song.

### 20.2 Behavior
- User triggers "Radio" from any clip's context menu or detail page.
- System finds clips matching genre, style, key, tempo, and mood.
- Results are drawn from the user's library and public catalog.
- Queue populates in the global player and auto-advances.

---

## 21. Get Full Song

### 21.1 Overview
Assembles a complete song from a short seed clip by automatically chaining extend operations.

### 21.2 Behavior
- Available on clips shorter than ~60 seconds.
- System plans a song structure (intro → verse → chorus → verse → chorus → bridge → outro).
- Executes sequential extend operations to reach ~3–4 minute target length.
- User can review and accept/reject individual sections.
- Final output is a single assembled clip.

---

## 22. Open in Editor (Pro)

### 22.1 Overview
Opens a clip in a waveform-level audio editor for precise manipulation. Pro feature.

### 22.2 Capabilities
- Waveform display with zoom and scroll.
- Cut, copy, paste, delete audio regions.
- Fade-in, fade-out, crossfade.
- Normalize, silence, and gain adjustment.
- Undo/redo stack.
- Non-destructive: original clip is preserved; edits create a new version.

---

## 23. Song Detail Page

**Route:** `/song/:id`

### 23.1 Content
- Full waveform player with scrubber.
- Song title, artist, style tags, generation parameters.
- Lyrics display (synchronized if available).
- Like / Dislike / Share / Publish controls.
- Comments section (if public).
- Related/similar songs panel.
- Full action menu (all edit/remix/export operations).
- Generation lineage (shows parent clips if this is a remix/extend/cover).

### 23.2 Metadata Display
| Field | Description |
|---|---|
| **Model** | Which AI model version generated the clip. |
| **BPM** | Detected or specified tempo. |
| **Key** | Musical key. |
| **Duration** | Length in mm:ss. |
| **Created** | Timestamp. |
| **Lineage** | Parent clip(s) if derived via remix/extend/cover. |
| **Mastering status** | Unmastered / Mastering in progress / Mastered. |
| **Distribution status** | Not distributed / Pending / Live on [platform]. |

---

## 24. Studio — Multi-Track DAW

**Route:** `/studio`

### 24.1 Overview
An in-browser multi-track digital audio workstation for arranging, layering, and mixing multiple clips into a complete production.

### 24.2 Track Types
- **AI-Generated Track:** Clip imported from workspace.
- **Audio Track:** Uploaded audio file (WAV, FLAC, MP3).
- **Sound/Loop Track:** Generated sounds (§5) placed on a timeline.
- **Vocal Track:** Isolated vocal from stems extraction.

### 24.3 Timeline & Arrangement
| Feature | Description |
|---|---|
| **Timeline** | Horizontal time ruler (bars + beats or mm:ss). |
| **Tracks** | Vertically stacked lanes. Drag clips onto tracks. |
| **Snap-to-grid** | Quantize clip placement to beat divisions. |
| **Loop regions** | Define a loop range for playback iteration. |
| **Markers** | Named position markers (e.g., "Verse 1," "Chorus"). |

### 24.4 Per-Track Controls
- Volume fader
- Pan knob
- Mute / Solo
- Track color label
- AI Regenerate (re-generate just this track's content with modified parameters)

### 24.5 Master Bus
- Master volume
- Basic EQ (low/mid/high shelf)
- Compressor (threshold, ratio, attack, release)
- Limiter
- Export mixdown (bounces all tracks to a single file)

### 24.6 Studio → Mastering Handoff
- "Send to Mastering" button on the master bus.
- Exports the mixdown as a WAV file and opens the Mastering Pipeline (§41).

### 24.7 Studio → DAW Export
- "Export for DAW" button.
- Exports individual track stems + a project metadata file (tempo, markers, track names).
- See §43 for full DAW export specification.

---

## 25. Custom Voice Models

### 25.1 Overview
Users can train personalized voice models (LoRA-based) from a small number of reference audio recordings (2–10 songs).

### 25.2 Training Workflow
1. User uploads 2–10 reference audio files containing the target voice.
2. System validates audio quality and consistency.
3. LoRA fine-tuning job is queued (consumes premium credits).
4. Training completes (estimated time displayed; typically minutes on GPU).
5. New voice model appears in the user's voice library.

### 25.3 Usage
- Select the custom voice in the "Add Voice" modal during creation (§6.2).
- Available across all creation modes (Simple, Advanced).
- Can be used in Cover (§12), Add Vocal (§18), and Extend (§11) workflows.
- Voice models are private to the creating user by default.

---

## Part II — Discovery & Social

---

## 26. Short-Form Audio/Video Feed

**Route:** `/feed`

### 26.1 Overview
A vertical-scroll, short-form feed of audio clips and music videos. Designed for discovery and engagement with bite-sized content.

### 26.2 Feed Item
- Full-screen (or large-card) audio/video player.
- Auto-plays on scroll-into-view.
- Song title, artist, style tags overlay.
- Like, share, remix, use-as-inspiration action buttons.
- Swipe/scroll to next item.

### 26.3 Feed Algorithm
- Personalized mix of trending clips, genre-matched recommendations, and followed-artist content.

---

## 27. Library (/me)

**Route:** `/me`

### 27.1 Sections
| Section | Description |
|---|---|
| **My Songs** | All generated, uploaded, and remixed clips. |
| **Liked** | Songs the user has liked. |
| **Playlists** | User-created playlists. |
| **Voice Models** | Custom trained voice models. |
| **Style Presets** | Saved style strings and lyrics presets. |
| **Mastering Queue** | Songs currently in the mastering pipeline. |
| **Releases** | Songs that have been distributed. |
| **Workspaces** | Project-oriented groupings of clips. |

---

## 28. Explore / Discovery

**Route:** `/explore`

### 28.1 Content
- **Trending** — Most liked/shared clips in the last 24h/7d.
- **Genre Channels** — Curated genre pages (Rock, Electronic, Hip Hop, Classical, etc.).
- **Staff Picks** — Editorially selected highlights.
- **New Releases** — Chronological feed of recently published songs.
- **Charts** — Top clips by plays, likes, or shares.

---

## 29. Search

**Route:** `/search`

### 29.1 Search Targets
- Song titles and lyrics
- Style tags and genres
- Artist/username
- Playlists

### 29.2 Filters
- Genre, BPM range, key, duration, creation date, model version.
- Sort by relevance, newest, most popular.

---

## 30. Playlists

### 30.1 Features
- Create, rename, delete playlists.
- Add/remove songs. Drag to reorder.
- Public or private visibility.
- Playlist cover art (auto-generated mosaic or custom upload).
- "Use as Inspiration" — feed entire playlist as generation context (§6.3).
- Share link.

---

## 31. Notifications

**Route:** `/notifications`

### 31.1 Notification Types
- Someone liked/shared your song.
- Someone remixed your song.
- New follower.
- Generation complete (for long-running jobs).
- Mastering job complete.
- Distribution status update (live on SoundCloud, etc.).
- System announcements (new features, model updates).

---

## 32. Profile Page

**Route:** `/@username`

### 32.1 Content
- Avatar, display name, bio.
- Style tags.
- Published songs grid.
- Playlists.
- Follower / following counts.
- Follow button (for other users viewing the profile).

---

## Part III — Publishing & Export

---

## 33. Publish & Visibility Controls

### 33.1 Visibility States
| State | Description |
|---|---|
| **Private** | Only visible to the creator. Default for all new clips. |
| **Unlisted** | Accessible via direct link but not shown in feeds/search. |
| **Public** | Visible in feeds, search, explore, and on the creator's profile. |

### 33.2 Publish Action
- Toggle from clip card, song detail page, or workspace.
- Publishing requires a title and at least one style tag.
- Optional: set cover art before publishing (see §35).

---

## 34. Download & Export

### 34.1 Audio Formats
| Format | Tier | Description |
|---|---|---|
| **MP3** (320kbps) | Free | Lossy compressed. |
| **WAV** (48kHz, 24-bit) | Pro | Lossless, production-quality. |
| **FLAC** | Pro | Lossless compressed. |
| **AAC** | Free | Lossy compressed, good for mobile. |
| **Opus** | Free | Modern lossy codec. |

### 34.2 Stems Download (Pro)
- Download individual stems: Vocals, Drums, Bass, Other (melody/harmony).
- Each stem is a separate WAV file.
- See §36 for stem extraction details.

### 34.3 Batch Export
- Select multiple clips in workspace.
- Export all as a ZIP archive with consistent naming.
- Includes metadata sidecar file (JSON) with BPM, key, style, lyrics.

---

## 35. Cover Art Generation

### 35.1 Overview
AI-generated cover art for songs, using the song's style/mood as visual context.

### 35.2 Workflow
1. User triggers "Generate Cover Art" from song detail or publish flow.
2. AI generates 4 cover art options based on song title, style tags, and lyrics.
3. User selects preferred art or regenerates.
4. Selected art is attached to the song metadata.

### 35.3 Custom Upload
- Alternatively, user uploads their own artwork.
- Minimum resolution: 3000×3000 pixels (distribution requirement).
- Accepted formats: JPG, PNG.

---

## 36. Stems & MIDI Extraction

### 36.1 Stem Separation
- Uses AI source separation to isolate: **Vocals**, **Drums**, **Bass**, **Other** (melody/harmony/effects).
- Input: any clip from workspace.
- Output: 4 separate WAV files (48kHz, 24-bit).
- Processing time: 30–120 seconds depending on clip length.

### 36.2 MIDI Extraction
- Analyzes audio and transcribes detected melodic/harmonic content to MIDI.
- Extraction targets: **Melody line**, **Chord progression**, **Drum pattern**, **Bass line**.
- Output: Standard MIDI file (.mid).
- Accuracy varies — works best with clear, separated sources (stems recommended as input over full mixes).

### 36.3 Usage in DAW Workflow
- Stems + MIDI together provide the full DAW import package.
- See §43 for the complete DAW export workflow.

---

## Part IV — AI Engine & Model Integration

---

## 37. AI Engine — ACE-Step-1.5

### 37.1 Overview
The platform runs on **ACE-Step-1.5**, an open-source music generation foundation model. The model is deployed locally and accessed via its REST API.

- **Repository:** github.com/frankbria/ACE-Step-1.5 (fork)
- **Architecture:** Hybrid LM (Composer Agent) + DiT (Diffusion Transformer) decoder
- **Output:** Stereo audio at 48kHz sample rate

### 37.2 Generation Modes
ACE-Step-1.5 supports six generation modes that map to platform features:

| Mode | Platform Feature | Description |
|---|---|---|
| **Text to Music** | Simple & Advanced Creation (§3, §4) | Natural language prompt → full song |
| **Cover** | Cover Workflow (§12) | Restyle existing audio while preserving melody |
| **Repaint** | Replace Section (§15) / Edit (§10.2) | Regenerate a selected time range |
| **Lego** | Studio layered generation (§24) | Build songs layer-by-layer, adding instruments progressively |
| **Extract** | Stems Extraction (§36) | Isolate individual instruments from a mix |
| **Complete** | Add Vocal (§18) | Add backing instruments or vocals to existing audio |

### 37.3 REST API Integration
- **Server launch:** `uv run acestep-api`
- **Default endpoint:** `http://localhost:8001`
- **Authentication:** Optional API key via `ACESTEP_API_KEY` environment variable

| Endpoint | Method | Description |
|---|---|---|
| `/release_task` | POST | Submit a generation job |
| `/query_result` | POST | Batch-query task status for multiple jobs |
| `/v1/stats` | GET | Server load and average job time |
| `/synth` | GET | Render audio codes to WAV (`?wav=1`) or MP3 |

### 37.4 Key API Parameters
| Parameter | Type | Description |
|---|---|---|
| `prompt` | string | Style/caption text |
| `lyrics` | string | Lyrics with optional structure tags |
| `vocal_language` | string | ISO 639-1 code or "unknown" for auto-detect |
| `inference_steps` | int | Quality/speed tradeoff (Turbo: 8, Standard: 32–64) |
| `thinking` | bool | Toggle Chain-of-Thought mode for richer control |
| `lm_temperature` | float | LM creativity control |
| `lm_cfg_scale` | float | LM guidance strength |
| `seed` | int | Reproducibility (-1 for random) |
| `model` | string | Model variant selection (for multi-model setups) |

### 37.5 Hardware Requirements
| Configuration | VRAM | Notes |
|---|---|---|
| **Standard (2B DiT)** | ~4GB (bf16), ~2.4GB (INT8) | Consumer GPUs (RTX 3060+) |
| **XL (4B DiT)** | ≥12GB (with offload+quantization) | RTX 3090/4090, A100 |
| **CPU-only** | N/A | Supported but significantly slower |
| **Apple Silicon** | MLX backend | Mac M1/M2/M3/M4 supported |

### 37.6 Output Formats
- WAV, WAV32, FLAC (default), MP3, Opus, AAC
- All output is stereo, 48kHz
- Format selectable per-request

### 37.7 Language Support
- 50+ languages for lyrics/vocals
- Strong support: English, Chinese, Japanese, Korean, Spanish, German, French, Portuguese, Italian, Russian
- Non-Roman scripts handled via stochastic romanization

---

## 37.8 Cloud Backend: ElevenLabs (Fallback / Alternative)

### 37.8.1 Overview
ElevenLabs Music Generation (`POST https://api.elevenlabs.io/v1/music`) is supported as a secondary backend for two use cases:
- **Auto-fallback:** When the local ACE-Step server is unreachable and `ELEVENLABS_API_KEY` is configured, generation falls back to ElevenLabs automatically with a user-visible warning.
- **Explicit selection:** User can force ElevenLabs via `--backend elevenlabs` for cloud-based generation without requiring a local GPU.

### 37.8.2 Configuration
| Variable | Description |
|---|---|
| `ELEVENLABS_API_KEY` | Required to enable ElevenLabs backend |
| `ELEVENLABS_OUTPUT_FORMAT` | Default: `mp3_44100_128` (see format table below) |

### 37.8.3 Supported Parameters (ElevenLabs subset)

When using the ElevenLabs backend, only the following generation parameters are supported. Unsupported parameters are ignored with a warning.

| acemusic Flag | ElevenLabs Field | Notes |
|---|---|---|
| `prompt` | `prompt` | Full support (max 4100 chars) |
| `--instrumental` | `force_instrumental: true` | Full support |
| `--duration` | `music_length_ms` | Full support (3s–600s) |
| `--style` (positive) | `composition_plan.positive_global_styles` | Requires `--backend elevenlabs`; switches to `composition_plan` mode |
| `--exclude-style` | `composition_plan.negative_global_styles` | Requires `composition_plan` mode |
| `--lyrics` (per section) | `composition_plan.sections[].lines` | Structured per-section; freeform `[Verse]` tags not supported |
| `--seed` | `seed` | Only available in `composition_plan` mode, not with `prompt` |
| `--format` | `output_format` query param | See format table below |

**Unsupported on ElevenLabs backend** (silently ignored, with warning printed to stderr):
`--bpm`, `--key`, `--time-signature`, `--vocal-language`, `--vocal-gender`, `--weirdness`, `--style-influence`, `--inference-steps`, `--thinking`, `--model`

### 37.8.4 Output Formats (ElevenLabs)
| Format value | Notes |
|---|---|
| `mp3_44100_128` | Default — works on all subscription tiers |
| `mp3_44100_192` | Requires Creator tier or above |
| `pcm_44100` | Lossless — requires Pro tier or above |
| `opus_48000_128` | Compressed, good quality |

Note: ElevenLabs outputs at 44.1kHz stereo. ACE-Step outputs at 48kHz. Files from different backends should not be mixed in the same project without resampling.

### 37.8.5 Limitations vs. ACE-Step
- Single model only (`music_v1`) — no Turbo/Standard/XL selection
- No audio reference input (no cover, remix, repaint, lego, or complete modes)
- No LoRA/custom voice model support
- No vocal language or gender control
- No BPM, key, or time signature constraints
- Seed only works in `composition_plan` mode (not with plain `prompt`)
- Maximum 2 clips per request (ElevenLabs generates 1 audio file per API call; call twice for 2 clips)

---

## 38. Model Configuration & Selection

### 38.1 Multi-Model Deployment
The platform can load multiple model variants simultaneously:
- Configure via `ACESTEP_CONFIG_PATH`, `ACESTEP_CONFIG_PATH2`, `ACESTEP_CONFIG_PATH3` environment variables.
- Select active model per-request via the `model` parameter.

### 38.2 Available Model Variants
| Variant | DiT Size | Speed | Quality | Best For |
|---|---|---|---|---|
| **Base** | 2B | Moderate | Good | General use |
| **SFT** | 2B | Moderate | Good+ | Better instruction following |
| **Turbo** | 2B | Fast (8 steps) | Good | Quick iteration, previews |
| **XL-Base** | 4B | Slow | Excellent | Final renders |
| **XL-SFT** | 4B | Slow | Excellent+ | Best instruction following |
| **XL-Turbo** | 4B | Moderate | Very Good | Fast high-quality |

### 38.3 Inference Configuration
| Setting | Turbo | Standard | XL |
|---|---|---|---|
| **Inference steps** | 8 | 32–64 | 32–64 |
| **Approx. time (A100)** | <2s | ~5s | ~15s |
| **Approx. time (RTX 3090)** | <10s | ~30s | ~60s |
| **VRAM (INT8)** | ~2.4GB | ~2.4GB | ~6GB |

---

## 39. LoRA Training & Personalization

### 39.1 Overview
Users can fine-tune the model using LoRA (Low-Rank Adaptation) to capture a specific voice or style from a small set of reference songs.

### 39.2 Training Parameters
| Parameter | Value |
|---|---|
| **Reference songs required** | 2–10 audio files |
| **Accepted formats** | WAV, FLAC, MP3 (16kHz+ sample rate) |
| **Training time** | Minutes on GPU (varies with dataset size) |
| **Output** | LoRA weights file attached to user account |
| **Storage** | Per-user model library (§25) |

### 39.3 Applications
- **Voice cloning:** Capture a specific vocal timbre/style.
- **Genre specialization:** Train on a set of songs in a niche genre for more authentic output.
- **Artist style:** Capture the production aesthetic of specific reference tracks.

---

## Part V — Music Video Creation

---

## 40. Music Video Generator

**Route:** `/video/:songId`

### 40.1 Overview
Generates a music video for a completed song, combining AI-generated visuals with the audio track.

### 40.2 Input
| Input | Description |
|---|---|
| **Source song** | Any clip from the user's workspace (completed/mastered preferred). |
| **Visual style prompt** | Natural language description of desired video aesthetic (e.g., "abstract neon landscapes," "cinematic city night shots," "anime-style narrative"). |
| **Reference images** | Optional uploaded images to guide the visual style. |
| **Lyrics sync** | Toggle — if enabled, lyrics appear as animated text overlays synced to the audio. |
| **Duration** | Matches song length automatically. |

### 40.3 Generation Options
| Option | Description |
|---|---|
| **Style presets** | Pre-configured visual themes: Abstract, Cinematic, Animated, Lyric Video, Live Performance, Nature. |
| **Scene transitions** | Auto (AI-driven), Cut, Fade, Dissolve. |
| **Aspect ratio** | 16:9 (landscape), 9:16 (vertical/social), 1:1 (square). |
| **Resolution** | 720p, 1080p (Pro), 4K (Pro). |
| **Frame rate** | 24fps, 30fps, 60fps. |

### 40.4 Output
- Rendered as MP4 (H.264 or H.265).
- Audio is muxed into the video file.
- Downloadable and publishable to the platform.
- Exportable for upload to YouTube, TikTok, Instagram.

### 40.5 Video Editing (Basic)
- Trim start/end.
- Replace individual scenes (regenerate a time range).
- Add/remove lyrics overlay.
- Adjust timing of scene transitions.

---

## Part VI — Mastering & Distribution Pipeline

---

## 41. Automated Mastering Pipeline

**Route:** `/release` → **Mastering** tab

### 41.1 Overview
Professional-grade automated mastering via external API services. Transforms a final mix into a distribution-ready master.

### 41.2 Mastering Service Integrations

#### 41.2.1 Dolby.io Music Mastering API (Primary)
- **Integration type:** REST API with Bearer JWT authentication
- **Input formats:** WAV, MP3, OGG, AAC, MP4
- **Output formats:** WAV, MP3, OGG, AAC, MP4 (all generated per call)
- **Features:** Multiple mastering profiles (up to 5 previews), loudness targeting, tonal optimization, stereo enhancement
- **Metrics returned:** Loudness (LUFS), EQ across 16 bands, stereo image analysis, codec info
- **Pricing:** Usage-based (per-minute of audio processed)

#### 41.2.2 LANDR Mastering API (Secondary)
- **Integration type:** REST API, B2B partnership access
- **Input formats:** WAV/AIFF recommended (all audio accepted)
- **Output formats:** Hi-Res MP3 (320kbps), WAV (16-bit), HD WAV (24-bit)
- **Features:** Three loudness settings, multiple mastering styles, genre-aware processing
- **Pricing:** From $2.50/track with volume discounts

#### 41.2.3 AI Mastering / Bakuage (Fallback)
- **Integration type:** Open REST API with OpenAPI spec
- **Base URL:** `https://api.bakuage.com:443`
- **Authentication:** Bearer token
- **Client SDKs:** JavaScript, Ruby, Go
- **Features:** Create mastering, get/list masterings, publish/download audio

### 41.3 Mastering Workflow
1. **Select song** — from workspace, or direct handoff from Studio mixdown (§24.6).
2. **Choose mastering profile:**
   - **Streaming** — optimized for Spotify/Apple Music (-14 LUFS).
   - **SoundCloud** — slightly louder for SoundCloud's normalization (-12 LUFS).
   - **Club/DJ** — maximum loudness for club play.
   - **Vinyl** — wider dynamic range for vinyl pressing.
   - **Custom** — user-specified LUFS target and style.
3. **Select mastering service** — Dolby.io (default), LANDR, or AI Mastering.
4. **Preview** — listen to up to 5 mastered previews with different profiles.
5. **Approve** — select preferred master. File is saved to workspace with "Mastered" badge.
6. **Compare** — A/B toggle between original mix and mastered version.

### 41.4 Mastering Status
- **Queued** — job submitted, waiting for processing.
- **Processing** — mastering engine working.
- **Preview Ready** — previews available for audition.
- **Approved** — user selected a master.
- **Failed** — error (retry available).

### 41.5 Batch Mastering
- Select multiple clips and apply the same mastering profile.
- Useful for album consistency.

---

## 42. Distribution & Release Management

**Route:** `/release` → **Distribute** tab

### 42.1 Overview
Packages mastered songs with metadata and artwork for distribution to streaming platforms and stores.

### 42.2 Distribution Channels

#### 42.2.1 SoundCloud (Direct API Integration)
- **Integration:** OAuth 2.1 authenticated API.
- **Upload endpoint:** `POST /tracks` (multipart/form-data, max 500MB).
- **Supported formats:** WAV, FLAC, MP3, OGG, AAC, AIFF.
- **Metadata fields:**

| Field | Required | Description |
|---|---|---|
| `title` | Yes | Song title |
| `genre` | Yes | Primary genre |
| `description` | No | Song description / liner notes |
| `bpm` | No | Tempo |
| `key_signature` | No | Musical key |
| `isrc` | No | International Standard Recording Code |
| `is_explicit` | No | Explicit content flag |
| `label_name` | No | Label or artist name |
| `license` | No | Creative Commons or All Rights Reserved |
| `artist` | No | Artist name |
| `sharing` | Yes | "public" or "private" |
| `artwork_data` | No | Cover art (uploaded as multipart data) |

- **Automation level:** Fully automated — upload, set metadata, publish.

#### 42.2.2 LANDR Distribution (Guided)
- **Integration:** No public API. Guided workflow within the platform.
- **Workflow:**
  1. Platform prepares a **distribution package** (mastered audio + metadata + artwork).
  2. User is guided to create/connect their LANDR account.
  3. Package is formatted to LANDR's requirements.
  4. User completes submission via LANDR's web interface (opened in-app or new tab).
- **Distribution targets:** Spotify, Apple Music, Amazon Music, YouTube Music, Tidal, Deezer, Pandora, 100+ platforms.

#### 42.2.3 DistroKid / TuneCore / CD Baby (Guided)
- **Integration:** No public APIs available from any major distributor.
- **Workflow:** Same guided approach as LANDR — platform prepares the package, user completes submission on the distributor's platform.

### 42.3 Release Package Preparation
The platform assembles all required assets:

| Asset | Specification |
|---|---|
| **Audio file** | Mastered WAV (16-bit/44.1kHz minimum, 24-bit/48kHz preferred) |
| **Cover art** | 3000×3000px minimum, JPG or PNG, no unauthorized logos/text |
| **Metadata** | Title, artist, album name, genre, release date, ISRC, UPC/EAN, copyright, explicit flag, language |
| **Lyrics** | Synced or unsynced lyrics (optional but recommended) |
| **Credits** | Producer, songwriter, performer credits |

### 42.4 Release Workflow
1. **Select song(s)** — single or album (multiple songs).
2. **Verify mastering** — must be mastered (§41). Platform warns if not.
3. **Set metadata** — form pre-populated from song detail; user reviews/edits.
4. **Cover art** — select existing or generate (§35). Resolution check enforced.
5. **ISRC/UPC** — auto-generate or enter existing codes.
6. **Choose distribution target(s)** — SoundCloud (auto), LANDR, DistroKid, etc. (guided).
7. **Review** — summary screen with all assets and metadata.
8. **Submit** — SoundCloud uploads automatically; others open guided flows.
9. **Track status** — notifications when songs go live on each platform.

### 42.5 Distribution Status Dashboard
| Status | Description |
|---|---|
| **Draft** | Release package in preparation. |
| **Ready** | All assets validated, ready for submission. |
| **Submitted** | Sent to distribution channel. |
| **In Review** | Platform reviewing (e.g., Spotify content review). |
| **Live** | Song is live and streaming. |
| **Rejected** | Platform rejected (reason displayed). |

---

## Part VII — DAW Integration & VST3 Plugin

---

## 43. DAW Export — Audio & MIDI

**Route:** Accessible from clip context menu → "Export to DAW" or Studio (§24.7)

### 43.1 Overview
Exports song assets in formats ready for import into professional DAWs (Cubase, Ableton Live, Logic Pro, FL Studio, etc.).

### 43.2 Export Formats

#### 43.2.1 Audio Export
| Format | Specs | Use Case |
|---|---|---|
| **WAV** | 48kHz, 24-bit, stereo | Standard DAW import |
| **WAV (32-bit float)** | 48kHz, 32-bit float | Maximum headroom for mixing |
| **FLAC** | 48kHz, 24-bit | Lossless with smaller file size |

#### 43.2.2 Stem Export
- Individual stems: **Vocals**, **Drums**, **Bass**, **Other** (melody/harmony/effects).
- Each stem as separate WAV file.
- All stems time-aligned and equal length for drop-in DAW use.

#### 43.2.3 MIDI Export
- Extracted MIDI data (§36.2): melody, chords, drums, bass.
- Standard MIDI file (.mid), Type 1 (multi-track).
- Tempo map and time signature embedded in MIDI header.
- Channel assignments: Ch 1 = Melody, Ch 2 = Chords, Ch 10 = Drums, Ch 3 = Bass.

### 43.3 DAW Project Metadata
Exported alongside audio/MIDI as a JSON sidecar file:

```json
{
  "project_name": "Song Title",
  "bpm": 120,
  "key": "C major",
  "time_signature": "4/4",
  "duration_seconds": 210,
  "stems": [
    {"name": "Vocals", "file": "vocals.wav"},
    {"name": "Drums", "file": "drums.wav"},
    {"name": "Bass", "file": "bass.wav"},
    {"name": "Other", "file": "other.wav"}
  ],
  "midi_files": [
    {"name": "Melody", "file": "melody.mid", "channel": 1},
    {"name": "Chords", "file": "chords.mid", "channel": 2},
    {"name": "Drums", "file": "drums.mid", "channel": 10},
    {"name": "Bass", "file": "bass.mid", "channel": 3}
  ],
  "markers": [
    {"name": "Verse 1", "time": 0.0},
    {"name": "Chorus", "time": 32.0},
    {"name": "Verse 2", "time": 64.0}
  ],
  "lyrics": "...",
  "style_tags": ["indie rock", "dreamy", "reverb-heavy"],
  "source_model": "ace-step-1.5-xl-sft",
  "generation_seed": 42
}
```

### 43.4 Cubase-Specific Integration
- **Import via stems + MIDI:** User imports WAV stems onto audio tracks and MIDI files onto instrument tracks in Cubase.
- **Tempo sync:** BPM and time signature from JSON sidecar should match the Cubase project settings. The platform displays recommended Cubase project settings.
- **Marker import:** Cubase supports marker track import via XML. Future: export a Cubase-compatible `.cpr` project stub or Track Archive (`.xml`).
- **MIDI CC data:** Include expression (CC11), modulation (CC1), and sustain (CC64) where detected.

### 43.5 Export Packaging
- All files bundled in a ZIP archive.
- Folder structure:
  ```
  SongTitle_Export/
  ├── audio/
  │   ├── full_mix.wav
  │   ├── vocals.wav
  │   ├── drums.wav
  │   ├── bass.wav
  │   └── other.wav
  ├── midi/
  │   ├── melody.mid
  │   ├── chords.mid
  │   ├── drums.mid
  │   └── bass.mid
  ├── project.json
  └── artwork.jpg
  ```

---

## 44. VST3 Plugin — DAW Bridge

### 44.1 Overview
A **VST3 plugin** that runs inside any VST3-compatible DAW (Cubase, Ableton Live, Logic via AU wrapper, FL Studio, etc.) and communicates with the locally-running AI engine to generate and import music directly within the DAW environment.

### 44.2 Technology Stack
| Component | Technology | Description |
|---|---|---|
| **Plugin framework** | JUCE (C++) | Industry-standard cross-platform audio plugin framework |
| **Plugin format** | VST3 (primary), AU (macOS secondary) | Broadest DAW compatibility |
| **Communication** | HTTP REST to `localhost:8001` | Plugin → local ACE-Step-1.5 API server |
| **Threading** | Dedicated non-audio thread for HTTP | Network I/O never blocks audio thread |
| **Platforms** | Windows, macOS, Linux | Matching ACE-Step-1.5 platform support |

### 44.3 Plugin UI

#### 44.3.1 Connection Status Panel
- **Server status indicator:** Green (connected), Yellow (connecting), Red (offline).
- **Server URL:** Editable text field (default `http://localhost:8001`).
- **API key:** Optional field for secured setups.
- **Model selector:** Dropdown populated from server's available models.
- **Test Connection** button.

#### 44.3.2 Generation Panel
| Control | Description |
|---|---|
| **Prompt textarea** | Style/caption text for generation. |
| **Lyrics textarea** | Lyrics with structure tags. Collapsible. |
| **Vocal Language** | Dropdown (50+ languages). |
| **Instrumental toggle** | Suppress vocals. |
| **BPM** | Auto-detect from DAW host tempo, or manual override. |
| **Key** | Auto-detect from DAW or manual. |
| **Duration** | Sync to DAW selection range, or manual input. |
| **Seed** | Random or fixed for reproducibility. |
| **Quality preset** | Turbo / Standard / High (maps to inference steps). |
| **Generate button** | Submits to local API. Progress bar shown. |

#### 44.3.3 Results Panel
- **Waveform preview** of generated clips (2 per generation).
- **Play/Stop** buttons for in-plugin preview (routed through DAW audio).
- **Insert to Track** — places the selected clip at the DAW playhead position on the plugin's track.
- **Send to New Track** — creates a new audio track in the DAW with the generated clip.
- **History** — scrollable list of previous generations in this session. Re-insert any past result.

#### 44.3.4 Import Panel
- **Import from Platform** — browse the user's workspace in the web app and pull clips into the DAW.
- **Import Audio** — load a local audio file into the plugin for Cover/Repaint operations.

### 44.4 DAW Integration Behaviors

#### 44.4.1 Tempo & Key Sync
- Plugin reads the DAW's host tempo (BPM) and auto-populates the generation BPM field.
- If the DAW has a key signature set, the plugin reads it.
- Generated audio is time-stretched/pitch-shifted if needed to match the DAW project exactly.

#### 44.4.2 Selection-Aware Generation
- If the user has a time selection in the DAW (e.g., bars 5–13), the plugin auto-sets the duration to match the selection length.
- "Generate & Insert" places the result precisely at the selection start.

#### 44.4.3 MIDI Input Mode
- Plugin can accept MIDI input from the DAW.
- User plays/records MIDI → plugin uses it as melodic input for the "Complete" generation mode.
- The generated audio replaces or layers alongside the MIDI performance.

#### 44.4.4 Sidechain Audio Input
- Plugin can receive audio from a sidechain input.
- The sidechain audio is used as a reference for Cover or Repaint modes.
- Allows remixing/re-styling existing DAW tracks in place.

### 44.5 Generation Modes Available in Plugin
| Mode | Plugin Control | Description |
|---|---|---|
| **Text to Music** | Prompt + optional lyrics | Full song generation |
| **Cover** | Sidechain input + new style prompt | Restyle an existing track |
| **Repaint** | Time selection + new prompt | Regenerate a section |
| **Complete** | MIDI input or sidechain + prompt | Add instruments/vocals to partial audio |
| **Lego** | Iterative — generate one layer at a time | Build up arrangement on separate tracks |

### 44.6 File Management
- Generated clips are cached locally in a configurable directory (default: `~/ACEStepPlugin/cache/`).
- Cache is browsable from the plugin's History panel.
- Export from plugin to platform workspace via API (push clips back to web app).

### 44.7 System Requirements
| Requirement | Specification |
|---|---|
| **ACE-Step-1.5 server** | Must be running locally (`uv run acestep-api`) |
| **GPU** | Required for server, not for the plugin itself |
| **DAW** | Any VST3-compatible host (Cubase 12+, Ableton 11+, FL Studio 21+, Reaper 7+) |
| **macOS** | AU version for Logic Pro compatibility |
| **Plugin size** | ~20MB installed (JUCE binary, no model weights) |

---

## Part VIII — Platform & Operations

---

## 45. Credits & Subscription System

### 45.1 Credit Costs (Indicative)
| Action | Credit Cost |
|---|---|
| Song generation (2 clips) | 1 credit |
| Extend | 1 credit |
| Cover | 1 credit |
| Mashup | 2 credits |
| Stem extraction | 1 credit |
| MIDI extraction | 1 credit |
| Remaster (in-app) | 0.5 credits |
| Mastering (external API) | 2–5 credits (varies by service) |
| LoRA training | 10 credits |
| Music video generation | 5–10 credits (varies by resolution/length) |
| SoundCloud distribution | 0 credits (included with Pro) |

### 45.2 Subscription Tiers
| Feature | Free | Pro |
|---|---|---|
| Credits per month | 50 | 500 |
| Audio download format | MP3 only | WAV, FLAC, all formats |
| Studio (multi-track) | View only | Full editing |
| Stems & MIDI export | No | Yes |
| Automated mastering | No | Yes |
| Distribution | No | SoundCloud auto + guided |
| VST3 plugin | Preview only | Full generation |
| Music video | 720p, watermarked | 1080p/4K, no watermark |
| Custom voice models | No | Yes |
| Priority generation queue | No | Yes |

---

## 46. Playback System (Global Player)

### 46.1 Layout
- Persistent bar at the bottom of the application.
- Visible on all pages.

### 46.2 Controls
| Control | Description |
|---|---|
| **Play / Pause** | Toggle playback of current clip. |
| **Previous / Next** | Navigate queue (playlist, radio, or workspace order). |
| **Progress bar** | Scrubber showing current position. Click to seek. |
| **Time display** | Current time / total duration (mm:ss). |
| **Volume** | Slider with mute toggle. |
| **Waveform** | Mini waveform visualization. |
| **Song info** | Title, artist, cover art thumbnail. Clickable → opens song detail page. |
| **Queue** | Button to view/edit the play queue. |
| **Repeat / Shuffle** | Toggle repeat (one/all) and shuffle mode. |
| **Like** | Quick-like from the player bar. |
| **A/B Compare** | Toggle between original and mastered versions (when available). |

---

## 47. Content Moderation & Reporting

### 47.1 Automated Moderation
- AI-based content screening on generation (filters harmful/prohibited content).
- Style prompt filtering for restricted terms.
- Lyrics scanning for policy violations.

### 47.2 User Reporting
- "Report" option on any public clip.
- Report categories: Inappropriate content, Copyright concern, Spam, Other.
- Reported content enters a review queue.

### 47.3 Appeals
- Users can appeal moderation decisions via account settings.

---

## 48. Experimental Features

**Route:** `/labs`

### 48.1 Overview
A space for beta and experimental features that are not yet production-ready.

### 48.2 Current Experiments
| Feature | Status | Description |
|---|---|---|
| **Sample from Song** | Beta | Extract and reuse song segments (§14). |
| **Real-time generation** | Alpha | Streaming audio generation with live parameter tweaking. |
| **Collaborative workspaces** | Alpha | Multiple users contributing to the same workspace. |
| **AI Arrangement** | Beta | Auto-arrange stems into a full song structure. |
| **Style Transfer** | Beta | Apply the production style of one song to another's content. |

---

## 49. Full UX Lifecycle Summary

### 49.1 Workflow A — In-App (Prompt to Distribution)

```
┌─────────────────────────────────────────────────────────────────┐
│  1. IDEATE                                                       │
│     Prompt (Simple/Advanced) → AI generates 2 clips              │
│                                                                   │
│  2. ITERATE                                                       │
│     Like/dislike → Regenerate → Adjust parameters                │
│     Extend → Cover → Remix → Mashup → Replace Section            │
│                                                                   │
│  3. PRODUCE                                                       │
│     Open in Studio → Arrange multi-track → Mix                   │
│     Or: Open in Editor → Fine-tune single clip                   │
│                                                                   │
│  4. ENHANCE                                                       │
│     Remaster (quick) or Send to Mastering Pipeline               │
│     Choose profile: Streaming / SoundCloud / Club / Custom       │
│     Preview → Approve mastered version                           │
│                                                                   │
│  5. VISUALIZE (Optional)                                          │
│     Generate music video → Select style → Render                 │
│                                                                   │
│  6. PACKAGE                                                       │
│     Set metadata (title, artist, genre, ISRC)                    │
│     Generate or upload cover art (3000×3000)                     │
│     Prepare release package                                      │
│                                                                   │
│  7. DISTRIBUTE                                                    │
│     SoundCloud → Automated upload via API                        │
│     LANDR / DistroKid / TuneCore → Guided submission             │
│     Track status → Notifications when live                       │
│                                                                   │
│  8. DISCOVER & SHARE                                              │
│     Publish on platform → Appears in feeds/search                │
│     Share links → Social media                                   │
│     Short-form feed → Community engagement                       │
└─────────────────────────────────────────────────────────────────┘
```

### 49.2 Workflow B — DAW Integration (Prompt to Cubase)

```
┌─────────────────────────────────────────────────────────────────┐
│  OPTION B1: Export from Web App → Import in DAW                  │
│                                                                   │
│  1. Create song in web app (Workflow A, steps 1–3)               │
│  2. Export to DAW (§43):                                         │
│     - Download stems (WAV, 48kHz/24-bit)                         │
│     - Download MIDI (melody, chords, drums, bass)                │
│     - Download project metadata (JSON)                           │
│  3. Import into Cubase:                                          │
│     - Set project BPM/key from metadata                          │
│     - Import stems onto audio tracks                             │
│     - Import MIDI onto instrument tracks                         │
│     - Continue production in Cubase                              │
│                                                                   │
│  OPTION B2: VST3 Plugin (Direct DAW Generation)                  │
│                                                                   │
│  1. Ensure ACE-Step-1.5 server is running locally                │
│  2. Load VST3 plugin on a DAW track                              │
│  3. Generate directly:                                           │
│     - Text-to-music with DAW tempo/key sync                      │
│     - Cover: sidechain existing track → restyle                  │
│     - Complete: feed MIDI input → get full audio                 │
│     - Lego: build layers one track at a time                     │
│  4. Insert generated audio onto DAW tracks                       │
│  5. Mix and produce entirely within the DAW                      │
│  6. Export final mix → feed back to web app for                  │
│     mastering and distribution (Workflow A, steps 4–7)           │
│                                                                   │
│  OPTION B3: Round-Trip                                           │
│                                                                   │
│  1. Start in web app → generate & iterate                        │
│  2. Export to DAW → add live instruments, fine-tune mix          │
│  3. Import DAW mixdown back to web app (Upload)                  │
│  4. Master via Mastering Pipeline                                │
│  5. Distribute via web app                                       │
└─────────────────────────────────────────────────────────────────┘
```

### 49.3 System Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     USER INTERFACES                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Web App     │  │  VST3 Plugin │  │  Mobile App (TBD)  │  │
│  │  (Next.js)   │  │  (JUCE/C++)  │  │                    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────┘  │
│         │                  │                                   │
│         ▼                  ▼                                   │
│  ┌─────────────────────────────────────────┐                  │
│  │         Platform API (FastAPI)          │                  │
│  │  Auth, Workspace, Metadata, Queue       │                  │
│  └──────────────────┬──────────────────────┘                  │
│                     │                                          │
│    ┌────────────────┼────────────────────┐                    │
│    ▼                ▼                    ▼                     │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐        │
│  │ACE-Step  │  │ Mastering    │  │  Distribution     │        │
│  │1.5 API   │  │ APIs         │  │  Services         │        │
│  │localhost  │  │ Dolby.io     │  │  SoundCloud API   │        │
│  │:8001     │  │ LANDR        │  │  LANDR (guided)   │        │
│  │          │  │ Bakuage      │  │  DistroKid (guided)│       │
│  └──────────┘  └──────────────┘  └──────────────────┘        │
│                                                                │
│  ┌─────────────────────────────────────────┐                  │
│  │         Data Layer                       │                  │
│  │  MongoDB (songs, users, metadata)        │                  │
│  │  Object Storage (audio files, stems)     │                  │
│  │  Local FS (ACE-Step cache, LoRA weights) │                  │
│  └─────────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────────┘
```

---

*End of specification.*
