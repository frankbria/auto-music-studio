## Layer 4: Advanced Integrations

*Goal: Extend the platform with music video generation, DAW-native creation via VST3 plugin, custom voice models, monetization, content safety, and production hardening.*

---

### Stage 22: Music Video Generator

**Overview:** Enable musicians to create AI-generated music videos from their songs. This stage integrates a backend video generation API, provides a dedicated video creation page, and includes basic editing tools — turning audio-only tracks into shareable visual content without leaving the platform.

**Spec Reference:** §40

---

#### US-22.1: Video Generation Backend Integration

**As a** developer, **I want** a backend service that communicates with an AI video generation API, **so that** the platform can render music videos from audio and visual prompts.

**Description:**
Integrate with an external AI video generation provider (e.g., Runway, Pika, or similar). The backend accepts a source audio file, a visual style prompt, optional reference images, and generation options, then submits a rendering job and tracks it to completion. This is the foundational plumbing for the entire video feature.

**Functional Requirements:**
- POST `/api/v1/videos/generate` accepts: songId, visual style prompt, reference image URLs, lyrics sync toggle, style preset, aspect ratio, resolution, frame rate, scene transitions
- Backend queues a rendering job to the video generation provider
- Job status endpoint: GET `/api/v1/videos/{jobId}/status` returns progress percentage, estimated time remaining, and current state (queued/rendering/encoding/complete/failed)
- On completion, the rendered MP4 is stored and associated with the source song
- Retry logic for transient provider failures
- Credit deduction (5–10 credits depending on resolution and duration) validated before submission

**Acceptance Criteria:**
- [ ] POST endpoint accepts valid parameters and returns a job ID
- [ ] Job status endpoint reports progress through all states to completion
- [ ] Completed video is a valid MP4 file with audio muxed in
- [ ] Insufficient credits returns a 402 error with explanation
- [ ] Provider failure triggers retry (up to 3 attempts) before marking as failed

---

#### US-22.2: Video Creation Page

**As a** musician, **I want** a dedicated video creation page where I can configure and generate a music video for my song, **so that** I have full control over the visual output.

**Description:**
The video page (`/video/:songId`) presents the source song, visual configuration options, and a generation trigger. The musician selects style, aspect ratio, resolution, and other options, then submits to generate.

**Functional Requirements:**
- Route: `/video/:songId` — loads the song's metadata, waveform, and cover art
- Source song card with playback controls, title, duration, and style tags
- Visual style prompt textarea for free-form description of desired video aesthetic
- Reference images upload (up to 5 images) to guide visual style
- Lyrics sync toggle — if enabled, lyrics appear as animated text overlays synced to the audio
- Style presets selector: Abstract, Cinematic, Animated, Lyric Video, Live Performance, Nature
- Aspect ratio picker: 16:9 (landscape), 9:16 (vertical/social), 1:1 (square)
- Resolution selector: 720p (Free), 1080p (Pro), 4K (Pro) — Pro options gated by subscription
- Frame rate: 24fps, 30fps, 60fps
- Scene transitions: Auto (AI-driven), Cut, Fade, Dissolve
- "Generate Video" button — disabled until source song is selected and at least a style prompt or preset is chosen
- Credit cost estimate displayed before submission

**Acceptance Criteria:**
- [ ] Page loads with song metadata and all configuration controls visible
- [ ] Style presets populate the style prompt with preset-specific text
- [ ] Pro-gated options (1080p, 4K) show a Pro badge and upgrade prompt for Free users
- [ ] Generate button submits to the backend and transitions to a progress view
- [ ] All aspect ratio and resolution combinations are selectable

---

#### US-22.3: Video Rendering Progress and Delivery

**As a** musician, **I want** to see real-time progress while my video renders and receive it when complete, **so that** I know the status and can plan accordingly.

**Description:**
Video rendering is a long-running job (minutes to tens of minutes depending on duration and resolution). The progress view keeps the musician informed and delivers the final video with download and publish options.

**Functional Requirements:**
- Progress view replaces the generation form after submission
- Progress bar with percentage, estimated time remaining, and current phase (analyzing audio, generating scenes, encoding)
- In-browser notification when rendering completes (even if the user navigated away)
- Video player with the rendered result, full playback controls
- Download button: MP4 (H.264 by default, H.265 for 4K)
- "Publish to Platform" button — makes the video publicly visible on the song detail page
- "Export for Social" — provides optimized versions for YouTube (16:9), TikTok/Reels (9:16), and Instagram (1:1)

**Acceptance Criteria:**
- [ ] Progress bar updates at least every 5 seconds during rendering
- [ ] Notification fires on completion if user navigated away
- [ ] Completed video is playable in-browser
- [ ] Download produces a valid MP4 with correct resolution and audio
- [ ] Publish makes the video visible on the song detail page

---

#### US-22.4: Basic Video Editing

**As a** musician, **I want** to make basic edits to my generated video, **so that** I can fix imperfect scenes without regenerating the entire video.

**Description:**
After a video is rendered, the musician can trim it, replace individual scenes (regenerate a time range), add or remove lyrics overlays, and adjust scene transition timing. These are non-destructive edits that produce a new version.

**Functional Requirements:**
- Trim controls: adjust start and end points of the video
- Scene replacement: select a time range, provide a new visual prompt, and regenerate only that section
- Lyrics overlay toggle: add or remove lyrics overlay post-generation
- Transition timing: drag scene transition markers to adjust cut points
- Each edit produces a new video version (original preserved)
- Edit history is maintained per video

**Acceptance Criteria:**
- [ ] Trimming produces a shorter video with clean cut points
- [ ] Scene replacement regenerates only the selected time range; surrounding video is preserved
- [ ] Adding lyrics overlay post-generation syncs text to audio
- [ ] Original video version is accessible after edits
- [ ] Edit history shows all versions with timestamps

---

### Stage 23: VST3 Plugin — Core

**Overview:** Build the foundational VST3 plugin using JUCE (C++) that connects to the locally-running ACE-Step-1.5 server. The plugin provides text-to-music generation inside any VST3-compatible DAW, with connection management, a generation panel, and a results panel for previewing and inserting clips. This brings the AI music engine directly into the musician's existing production workflow.

**Spec Reference:** §44.1–44.3, §44.6, §44.7

---

#### US-23.1: JUCE Project Setup and Cross-Platform Build

**As a** developer, **I want** a JUCE-based VST3 plugin project that builds on Windows, macOS, and Linux, **so that** we have a solid foundation for the DAW integration features.

**Description:**
Set up the JUCE project in the `plugin/` directory of the monorepo. Configure CMake for cross-platform builds producing VST3 as the primary format and AU as a secondary format for macOS. The plugin should load in a DAW and display a minimal UI.

**Functional Requirements:**
- JUCE project in `plugin/` with CMakeLists.txt
- Build targets: VST3 (all platforms), AU (macOS only)
- CI build verification for Windows (MSVC), macOS (Xcode/clang), Linux (GCC)
- Plugin loads in a DAW host without crashing (validated with pluginval or equivalent)
- Minimal placeholder UI renders (plugin name, version, empty panels)
- Installed binary size target: ~20MB
- Non-audio thread infrastructure for HTTP communication (no network calls on audio thread)

**Acceptance Criteria:**
- [ ] VST3 builds successfully on all three platforms
- [ ] AU builds on macOS
- [ ] Plugin passes pluginval validation
- [ ] Plugin loads in at least one DAW (Reaper recommended for testing) and shows UI
- [ ] Binary size is under 25MB

---

#### US-23.2: Connection Status Panel

**As a** musician, **I want** to configure and verify the connection to my local ACE-Step server from within the plugin, **so that** I know the AI engine is ready before I try to generate.

**Description:**
The connection panel is the first thing a musician sees when opening the plugin. It shows the server URL, API key field, model selector, connection test button, and a clear status indicator. The plugin requires a running ACE-Step-1.5 server at `localhost:8001` (configurable).

**Functional Requirements:**
- Server URL text field (default: `http://localhost:8001`)
- API key text field (optional, for secured setups)
- "Test Connection" button — calls the server's health endpoint
- Status indicator: Green (connected, model loaded), Yellow (connecting/testing), Red (offline/error)
- Model selector dropdown — populated from the server's available models on successful connection
- Connection settings persist between DAW sessions (saved to local config file)
- Auto-connect on plugin load (non-blocking, updates indicator when complete)

**Acceptance Criteria:**
- [ ] With ACE-Step running: Test Connection shows green indicator and populates model list
- [ ] With ACE-Step stopped: Test Connection shows red indicator with "Server unreachable" message
- [ ] Custom server URL is saved and restored across DAW sessions
- [ ] Model dropdown lists all available models from the server
- [ ] Auto-connect attempt occurs on plugin load without blocking the DAW

---

#### US-23.3: Generation Panel

**As a** musician, **I want** to enter a prompt, configure generation parameters, and trigger music generation from inside my DAW, **so that** I can create AI music without leaving my production environment.

**Description:**
The generation panel mirrors the core creation controls from the web app — prompt, lyrics, vocal language, instrumental toggle, BPM, key, duration, seed, and quality preset. The musician fills in the fields and clicks Generate. The request is sent via HTTP REST on a non-audio thread.

**Functional Requirements:**
- Prompt textarea for style/caption text
- Lyrics textarea (collapsible) with support for structure tags ([Verse], [Chorus], etc.)
- Vocal language dropdown (50+ languages)
- Instrumental toggle
- BPM field (numeric input, or "Auto")
- Key selector ("Any" or specific musical key)
- Duration field (seconds, numeric input)
- Seed field (numeric or "Random")
- Quality preset selector: Turbo / Standard / High (maps to inference steps)
- Generate button — submits to the ACE-Step REST API via non-audio HTTP thread
- Progress bar during generation (polls job status)
- Generation disabled when connection status is Red
- Text-to-Music and Cover modes selectable via a mode toggle

**Acceptance Criteria:**
- [ ] Filling in a prompt and clicking Generate produces 2 audio clips
- [ ] Progress bar updates during generation and completes when clips are ready
- [ ] All parameter fields are sent correctly to the API (verified via request logging)
- [ ] Generation does not cause audio dropouts or DAW UI freezing
- [ ] Cover mode accepts a source audio reference

---

#### US-23.4: Results Panel and Clip Insertion

**As a** musician, **I want** to preview generated clips and insert them into my DAW timeline, **so that** I can use AI-generated audio alongside my existing tracks.

**Description:**
After generation completes, the results panel shows waveform previews of the 2 generated clips. The musician can play/stop each clip, then insert it at the DAW playhead position or send it to a new track.

**Functional Requirements:**
- Waveform visualization for each of the 2 generated clips
- Play/Stop buttons per clip (audio routed through the DAW's audio engine)
- "Insert to Track" button — places the selected clip at the DAW playhead position on the plugin's track
- "Send to New Track" button — creates a new audio track in the DAW containing the clip
- Generation history: scrollable list of all generations in this session, with the ability to re-insert any past result
- Generated clips cached locally at `~/ACEStepPlugin/cache/` (configurable)
- Cache is browsable from the history panel

**Acceptance Criteria:**
- [ ] Both generated clips display waveform previews
- [ ] Play/Stop works for each clip within the DAW
- [ ] "Insert to Track" places audio at the correct playhead position
- [ ] History panel shows all generations from the current session
- [ ] Clips are persisted in the local cache directory and survive plugin close/reopen

---

#### US-23.5: Local Cache and File Management

**As a** musician, **I want** my generated clips stored locally and managed efficiently, **so that** I can access past generations without regenerating.

**Description:**
The plugin maintains a local file cache for all generated clips. The cache is organized, browsable, and configurable. This keeps the plugin lightweight (~20MB binary) while audio data lives on disk.

**Functional Requirements:**
- Default cache directory: `~/ACEStepPlugin/cache/`
- Configurable cache path via plugin settings
- Cache organized by date and generation ID
- Cache browser in the plugin UI showing past generations with metadata (prompt, date, duration)
- Delete individual cached clips or clear entire cache
- Total cache size displayed in settings
- Cache is independent of the web platform — no account required for local-only usage

**Acceptance Criteria:**
- [ ] Generated clips appear in the cache directory after generation
- [ ] Cache browser lists clips with correct metadata
- [ ] Deleting a cached clip removes it from disk and the browser
- [ ] Custom cache path is respected after configuration change
- [ ] Cache size is reported accurately in settings

---

### Stage 24: VST3 Plugin — Advanced

**Overview:** Enhance the VST3 plugin with deep DAW integration features — tempo/key sync, selection-aware generation, MIDI input, sidechain audio input, Lego mode, and bidirectional sync with the web platform. These features make the plugin feel native to the DAW workflow rather than a bolted-on tool.

**Spec Reference:** §44.4–44.5

---

#### US-24.1: DAW Tempo and Key Sync

**As a** musician, **I want** the plugin to automatically detect my DAW's BPM and key, **so that** generated music matches my project without manual configuration.

**Description:**
The plugin reads the host DAW's tempo and key signature and auto-populates the generation fields. Generated audio is time-stretched or pitch-shifted if needed to match the DAW project exactly. This removes friction and ensures every generation is immediately usable in context.

**Functional Requirements:**
- Read host BPM via JUCE's `getPlayHead()->getPosition()` API
- Read host key signature if available
- Auto-populate BPM and Key fields in the generation panel (overridable by the musician)
- "Sync" indicator shows when fields are auto-populated vs. manually set
- If DAW tempo changes during a session, the fields update accordingly
- Generated audio is time-stretched to match host BPM if the generation result differs slightly

**Acceptance Criteria:**
- [ ] Opening the plugin in a 120 BPM project auto-fills the BPM field with 120
- [ ] Changing the DAW tempo updates the plugin's BPM field
- [ ] Generated clip at 118 BPM is time-stretched to 120 BPM on insertion
- [ ] Manual BPM override disables auto-sync with a visual indicator

---

#### US-24.2: Selection-Aware Generation

**As a** musician, **I want** the plugin to use my DAW's time selection to set generation duration and insertion point, **so that** I can generate audio that fits exactly where I need it.

**Description:**
When the musician has a time selection in the DAW (e.g., bars 5–13), the plugin reads it, auto-sets the duration to match the selection length, and offers a "Generate & Insert" button that places the result precisely at the selection start.

**Functional Requirements:**
- Detect DAW time selection (start and end position) via host transport API
- Auto-set duration field to match selection length in seconds
- "Generate & Insert" button: generates and places result at the selection start on the plugin's track
- Selection info displayed in the generation panel (e.g., "Selection: bars 5–13, 16.0s")
- Works with no selection — falls back to manual duration and playhead insertion
- Duration field shows both the auto-detected value and allows manual override

**Acceptance Criteria:**
- [ ] Selecting bars 5–13 in the DAW auto-sets duration to the correct number of seconds
- [ ] "Generate & Insert" places audio starting at bar 5
- [ ] With no selection, the plugin behaves as in Stage 23 (manual duration, playhead insertion)
- [ ] Selection info is displayed correctly in the generation panel

---

#### US-24.3: MIDI Input and Sidechain Audio

**As a** musician, **I want** to feed MIDI or audio from my DAW into the plugin as creative input, **so that** I can use my own performances and existing tracks as seeds for AI generation.

**Description:**
The plugin accepts MIDI input from the DAW for "Complete" generation mode (turning a MIDI sketch into full audio) and sidechain audio input for Cover/Repaint modes (restyling an existing DAW track). These inputs deeply integrate AI generation into the production workflow.

**Functional Requirements:**
- MIDI input mode: plugin receives MIDI from the DAW (played or recorded)
- Captured MIDI is used as melodic input for the "Complete" generation mode
- "Record MIDI" toggle captures incoming MIDI to a buffer for submission
- Sidechain audio input: receive audio from a sidechain bus/send
- "Capture Sidechain" records sidechain audio for use as reference in Cover or Repaint modes
- Mode selector includes: Text to Music, Cover (sidechain), Complete (MIDI), Repaint (sidechain + time range)
- Clear indicators showing when MIDI or sidechain audio has been captured and is ready for generation

**Acceptance Criteria:**
- [ ] Playing MIDI into the plugin captures it and enables "Complete" mode generation
- [ ] Sidechain audio from another track is captured and usable as Cover reference
- [ ] Generated audio from MIDI input reflects the melodic content of the MIDI performance
- [ ] Cover mode with sidechain input produces a restyled version of the reference audio
- [ ] Mode selector correctly shows available modes based on captured inputs

---

#### US-24.4: Lego Mode and Layer-by-Layer Generation

**As a** musician, **I want** to build up a song layer by layer, generating one instrument or part at a time, **so that** I have fine-grained control over the arrangement.

**Description:**
Lego mode enables iterative layer-by-layer generation. The musician generates a drum track, then a bass line that fits the drums, then a melody on top, each on a separate DAW track. Each layer is generated with awareness of what exists already.

**Functional Requirements:**
- "Lego Mode" toggle in the generation panel
- In Lego mode, existing audio on the plugin track (or sidechain) is sent as context for the next generation
- Each generated layer is placed on a separate new track
- Layer order is tracked: the musician can regenerate any layer while keeping others
- Prompt for each layer specifies the instrument or part (e.g., "add a funky bass line")
- Context audio is mixed down and sent as reference to the API

**Acceptance Criteria:**
- [ ] Generating a drum layer, then a bass layer, produces two tracks where the bass fits the drums
- [ ] Each layer is placed on its own track in the DAW
- [ ] Regenerating one layer does not affect other layers
- [ ] Context audio is audibly reflected in the generated layer (musical coherence)

---

#### US-24.5: Platform Integration and Clip Sync

**As a** musician, **I want** to browse my web platform workspace from the plugin and push DAW clips back to the platform, **so that** my work flows seamlessly between the DAW and the web app.

**Description:**
The plugin connects to the web platform API (when authenticated) to import clips from the musician's workspace into the DAW and push locally generated clips back to the web app. This creates a bidirectional bridge between desktop production and the cloud platform.

**Functional Requirements:**
- "Import from Platform" panel: browse workspaces and clips from the web app
- Search and filter clips by title, style, date
- Download selected clip and insert into DAW track
- "Push to Platform" button on any cached clip: uploads to the musician's web app workspace
- Authentication via API key or OAuth token stored in plugin settings
- Platform sync is optional — plugin works fully offline with local ACE-Step server

**Acceptance Criteria:**
- [ ] Authenticated plugin displays the musician's web app workspaces and clips
- [ ] Importing a platform clip downloads and inserts it into the DAW
- [ ] Pushing a local clip uploads it to the web app workspace with metadata
- [ ] Plugin works without platform authentication (local-only mode)
- [ ] Connection errors to the platform do not affect local generation

---

### Stage 25: Custom Voice Models

**Overview:** Allow musicians to train personalized voice models from a small set of reference recordings. Trained models are usable across all creation modes — Simple, Advanced, Cover, Add Vocal, and Extend. Voice models are private by default and stored in a per-user library.

**Spec Reference:** §25, §39

---

#### US-25.1: Voice Model Training Backend

**As a** musician, **I want** to upload reference audio files and train a custom voice model, **so that** generated songs can use my unique vocal style.

**Description:**
The backend accepts 2–10 reference audio files, validates their quality and consistency, and queues a LoRA fine-tuning job. The resulting voice model weights are stored in the user's private voice library. Training consumes premium credits (10 credits).

**Functional Requirements:**
- POST `/api/v1/voice-models/train` accepts: 2–10 audio files (WAV, FLAC, MP3 at 16kHz+ sample rate), model name, optional description
- Validation: minimum 2 files, maximum 10, audio quality check (sample rate, duration, noise level), consistency check (similar vocal characteristics across files)
- Training job queued with estimated time (typically minutes on GPU)
- Credit validation: 10 credits deducted before training begins; insufficient credits returns 402
- On completion, LoRA weights file stored and associated with the user's account
- On failure, credits are refunded and error details are returned

**Acceptance Criteria:**
- [ ] Uploading 3 valid audio files and triggering training returns a job ID
- [ ] Validation rejects files below 16kHz sample rate with a clear error message
- [ ] Training job completes and produces a usable voice model
- [ ] 10 credits are deducted on submission; refunded on failure
- [ ] Uploading 1 file or 11 files returns a validation error

---

#### US-25.2: Training Progress and Notifications

**As a** musician, **I want** to track my voice model training progress and be notified when it completes, **so that** I know when my voice is ready to use.

**Description:**
Voice model training takes minutes to complete. The platform provides progress tracking and notifications so the musician can continue other work while training runs.

**Functional Requirements:**
- GET `/api/v1/voice-models/train/{jobId}/status` returns: progress percentage, estimated time remaining, current phase (uploading, preprocessing, training, finalizing)
- In-app notification on completion (success or failure)
- Email notification (optional, based on user notification preferences)
- Training progress visible in the voice library page
- If the user navigates away and returns, progress is restored

**Acceptance Criteria:**
- [ ] Status endpoint returns progress updates during training
- [ ] In-app notification fires on training completion
- [ ] Progress is visible in the voice library UI
- [ ] Returning to the page after navigation restores the current progress state

---

#### US-25.3: Voice Model Library

**As a** musician, **I want** a library to manage my trained voice models, **so that** I can organize, rename, and delete my custom voices.

**Description:**
Each user has a private voice model library accessible from the Library section of the platform. Models can be listed, renamed, deleted, and previewed.

**Functional Requirements:**
- GET `/api/v1/voice-models` returns all voice models for the authenticated user
- DELETE `/api/v1/voice-models/{id}` removes a voice model and its stored weights
- PATCH `/api/v1/voice-models/{id}` allows renaming and updating description
- Voice library page in the Library section (`/me` → Voices tab)
- Each voice card shows: name, description, creation date, number of reference files, training status
- Preview: generate a short sample clip using the voice model
- Voice models are private by default (not visible to other users)

**Acceptance Criteria:**
- [ ] Voice library page lists all trained voice models
- [ ] Renaming a voice model updates it everywhere it appears
- [ ] Deleting a voice model removes it from the library and frees storage
- [ ] Preview generates a short audio clip using the selected voice
- [ ] Other users cannot see or access another user's voice models

---

#### US-25.4: Voice Selection in Creation Modes

**As a** musician, **I want** to select a custom voice model when creating songs in any mode, **so that** all my music can feature my unique vocal style.

**Description:**
Custom voice models appear as an option in all creation forms — Simple, Advanced, Cover, Add Vocal, and Extend. An "Add Voice" modal lets the musician browse their voice library and attach a voice to the generation.

**Functional Requirements:**
- "Add Voice" button in the creation form opens a voice selection modal
- Modal lists all trained voice models with name, preview button, and select button
- Selected voice is shown as a pill/badge in the creation form
- Voice selection is available in: Simple mode, Advanced mode, Cover workflow, Add Vocal workflow, Extend workflow
- Voice parameter sent to the generation API alongside other parameters
- "Remove Voice" option to clear the selection and use the default model voice
- Voice selector also available in the VST3 plugin (if authenticated with the platform)

**Acceptance Criteria:**
- [ ] Voice selection modal appears and lists all trained voices
- [ ] Selecting a voice and generating produces audio with the custom vocal timbre
- [ ] Voice selection works in all five creation modes
- [ ] Removing voice selection reverts to the default model voice
- [ ] Generation without a custom voice works as before (no regressions)

---

### Stage 26: Credits & Subscription System

**Overview:** Implement the credit-based usage tracking and subscription tier system. Every generative action consumes credits. Free users get a limited monthly allocation; Pro users get more credits and unlock advanced features. This stage adds payment integration, feature gating, and a usage dashboard.

**Spec Reference:** §45

---

#### US-26.1: Credit Tracking and Deduction

**As a** musician, **I want** my credits tracked accurately per action, **so that** I know what each generation costs and how many credits I have left.

**Description:**
Every generative action has a defined credit cost. The system deducts credits atomically before processing begins and displays the remaining balance. If the musician has insufficient credits, the action is denied with a clear explanation.

**Functional Requirements:**
- Credit costs per action: generation (1), extend (1), cover (1), mashup (2), stems (1), MIDI (1), remaster (0.5), mastering (2–5), LoRA training (10), video (5–10)
- Credits are deducted atomically before the job begins (no double-deduction on retry)
- GET `/api/v1/credits/balance` returns current credit balance
- Credit balance displayed in the app header/sidebar at all times
- Insufficient credits returns 402 with: required credits, current balance, and upgrade prompt
- Credit refund on job failure (automatic)

**Acceptance Criteria:**
- [ ] Generating a song deducts exactly 1 credit
- [ ] Mashup deducts exactly 2 credits
- [ ] Attempting an action with insufficient credits returns a 402 with clear messaging
- [ ] Failed jobs result in automatic credit refund
- [ ] Credit balance is visible at all times and updates in real time after each action

---

#### US-26.2: Subscription Tiers and Feature Gating

**As a** musician, **I want** to understand what my subscription tier includes and see clear prompts to upgrade when I hit a limit, **so that** I can make informed decisions about my plan.

**Description:**
Two tiers exist: Free (50 credits/month, limited features) and Pro (500 credits/month, all features). Pro-only features show a Pro badge and an upgrade prompt for Free users. Feature gating is enforced both on the frontend (UI indicators) and backend (API authorization).

**Functional Requirements:**
- Free tier: 50 credits/month, MP3 download only, Studio view-only, no stems/MIDI export, no mastering, no distribution, VST3 preview-only, 720p watermarked video, no custom voice models
- Pro tier: 500 credits/month, all formats, full Studio editing, stems/MIDI, mastering, distribution, full VST3, 1080p/4K video, custom voice models, priority queue
- Pro badge displayed on locked features in the UI
- Clicking a locked feature shows an upgrade modal explaining the benefit
- Backend enforces tier restrictions — Free users hitting Pro endpoints receive 403 with upgrade guidance
- Credits reset monthly on the subscription anniversary date

**Acceptance Criteria:**
- [ ] Free user sees Pro badges on restricted features
- [ ] Free user clicking a Pro feature sees an upgrade modal (not an error)
- [ ] Pro user can access all features without restriction
- [ ] API returns 403 for Free users attempting Pro-only actions
- [ ] Credits reset to tier allocation on monthly anniversary

---

#### US-26.3: Payment Integration

**As a** musician, **I want** to subscribe, cancel, and manage my payment method, **so that** I can upgrade to Pro and manage my billing.

**Description:**
Integrate with a payment provider (Stripe or similar) for subscription management. The musician can subscribe to Pro, update their payment method, cancel their subscription, and switch between tiers.

**Functional Requirements:**
- Subscribe to Pro: redirects to payment provider's checkout flow
- Payment methods: credit/debit card, with potential for additional methods
- Cancel subscription: takes effect at end of current billing period (no immediate feature loss)
- Upgrade from Free to Pro: immediate access to Pro features, prorated first month
- Downgrade from Pro to Free: takes effect at end of billing period
- Billing history accessible from account settings
- Webhook handler for payment events (successful charge, failed charge, subscription canceled)

**Acceptance Criteria:**
- [ ] Subscribing to Pro via checkout flow activates Pro features immediately
- [ ] Canceling retains Pro access until the end of the billing period
- [ ] Failed payment triggers a grace period with retry before downgrade
- [ ] Billing history shows all past charges with dates and amounts
- [ ] Webhook correctly processes payment events and updates user tier

---

#### US-26.4: Credit Top-Up Purchase

**As a** musician, **I want** to buy additional credits when I run out, **so that** I can keep creating without waiting for my monthly reset.

**Description:**
Both Free and Pro users can purchase credit top-up packs. Purchased credits do not expire and are used after the monthly allocation is exhausted.

**Functional Requirements:**
- Credit packs available: 50 credits, 100 credits, 250 credits (pricing TBD)
- Purchase flow via payment provider (one-time charge, not recurring)
- Purchased credits are additive and do not expire
- Monthly credits are consumed first; purchased credits are consumed after monthly allocation is depleted
- Purchase history visible in the usage dashboard
- Credit pack purchase available from the upgrade modal and the usage dashboard

**Acceptance Criteria:**
- [ ] Purchasing a credit pack increases the credit balance by the correct amount
- [ ] Monthly credits are consumed before purchased credits
- [ ] Purchased credits persist across monthly resets (do not expire)
- [ ] Purchase history is visible in the usage dashboard

---

#### US-26.5: Usage Dashboard

**As a** musician, **I want** to see my credit usage history and breakdown by category, **so that** I can understand my usage patterns and plan accordingly.

**Description:**
A usage dashboard shows remaining credits, usage history over time, and breakdown by action category (generation, editing, mastering, video, etc.).

**Functional Requirements:**
- Usage dashboard accessible from account settings or sidebar
- Display: credits remaining (monthly + purchased), days until reset, current tier
- Usage chart: daily or weekly credit consumption over the past 30 days
- Category breakdown: pie/bar chart showing credits spent per action type
- Usage history table: date, action type, clip title, credits consumed
- Export usage data as CSV

**Acceptance Criteria:**
- [ ] Dashboard shows accurate credit balance and reset date
- [ ] Usage chart reflects actual credit consumption over time
- [ ] Category breakdown correctly attributes credits to action types
- [ ] Usage history lists all credit-consuming actions
- [ ] CSV export contains complete usage data

---

### Stage 27: Content Moderation

**Overview:** Implement automated content screening, user reporting, admin moderation tools, and an appeals workflow. This stage ensures the platform is safe and trustworthy for all users — filtering harmful content at generation time, providing reporting mechanisms, and giving admins the tools to manage issues.

**Spec Reference:** §47

---

#### US-27.1: Automated Content Screening

**As an** admin, **I want** AI-based content screening on all generation requests, **so that** harmful or prohibited content is filtered before it reaches the platform.

**Description:**
All generation requests pass through an automated screening layer that checks prompts, style descriptors, and lyrics for policy violations. Flagged content is blocked with an explanation; borderline content may be flagged for review.

**Functional Requirements:**
- Prompt filtering: scan style prompts for restricted terms and prohibited content categories
- Lyrics scanning: check lyrics for policy violations (hate speech, explicit violence, prohibited content)
- Screening runs before credits are deducted and before the generation job is submitted
- Blocked requests return a clear, non-accusatory message explaining why the content was not generated
- Borderline content is flagged for admin review but allowed to generate (with a flag on the clip)
- Screening rules are configurable by admin (allow-lists, block-lists, sensitivity thresholds)
- False positive rate should be minimized — creative expression is prioritized

**Acceptance Criteria:**
- [ ] A prompt containing clearly prohibited content is blocked with an explanation
- [ ] A normal creative prompt passes screening without delay
- [ ] Borderline content is flagged but still generates
- [ ] Blocked requests do not consume credits
- [ ] Admin can adjust screening rules without a code deploy

---

#### US-27.2: User Reporting

**As a** listener, **I want** to report public clips that violate community guidelines, **so that** I can help keep the platform safe.

**Description:**
Any public clip can be reported by any authenticated user. The report includes a category and optional details, and enters a moderation review queue.

**Functional Requirements:**
- "Report" button on every public clip (song detail page, feed, explore, search results)
- Report modal with categories: Inappropriate content, Copyright concern, Spam, Other
- Optional free-text field for additional details
- Submission confirmation message ("Report received. Our team will review it.")
- Duplicate reports from the same user on the same clip are prevented
- Reports create entries in the admin moderation queue

**Acceptance Criteria:**
- [ ] Clicking "Report" opens the report modal with category options
- [ ] Submitting a report shows a confirmation message
- [ ] The report appears in the admin moderation queue
- [ ] Submitting a duplicate report shows "You have already reported this clip"
- [ ] Reports are available for all public clip surface areas (detail page, feed, explore)

---

#### US-27.3: Admin Moderation Dashboard

**As an** admin, **I want** a dashboard to review reported content and take action, **so that** I can maintain community safety efficiently.

**Description:**
The admin moderation dashboard shows a queue of reported and flagged content, with tools to review, approve, remove, or escalate. Admins can also ban users who repeatedly violate guidelines.

**Functional Requirements:**
- Admin route: `/admin/moderation` (accessible only to admin role)
- Review queue: list of reported clips sorted by report count and severity
- Each queue item shows: clip details (title, creator, style, audio player), report count, report categories, flagging source (user report vs. automated)
- Actions per item: Approve (dismiss reports), Remove (take down the clip, notify creator), Flag (add a warning label visible to listeners)
- User actions: Warn user (send a notification), Ban user (disable account, remove all public content)
- Bulk actions: select multiple items and apply the same action
- Moderation activity log for audit trail

**Acceptance Criteria:**
- [ ] Admin sees all reported clips in a sortable, filterable queue
- [ ] Approving a report clears it from the queue
- [ ] Removing a clip makes it inaccessible publicly and notifies the creator
- [ ] Banning a user disables their account and removes public content
- [ ] Moderation log records all admin actions with timestamps

---

#### US-27.4: Appeals Workflow

**As a** musician, **I want** to appeal a moderation decision on my content, **so that** I can have unfair takedowns reviewed.

**Description:**
When a musician's content is removed or their account is restricted, they can submit an appeal through their account settings. Appeals enter a separate review queue for admin evaluation.

**Functional Requirements:**
- Appeal option on any removed or flagged clip in the musician's Library (visible only to the clip owner)
- Appeal form: reason for appeal (free text), optional supporting context
- Appeal submission creates an entry in the admin appeals queue
- Admin can: Uphold decision (deny appeal), Reverse decision (restore content, notify musician), Request more information
- Musician receives notification of the appeal outcome
- One appeal per moderation action (no repeat appeals for the same decision)

**Acceptance Criteria:**
- [ ] Musician sees "Appeal" option on removed clips in their Library
- [ ] Submitting an appeal shows confirmation and creates an admin queue entry
- [ ] Admin can uphold or reverse the decision from the appeals queue
- [ ] Musician receives notification of the outcome
- [ ] Repeat appeal on the same decision is blocked

---

### Stage 28: Polish & Production Readiness

**Overview:** Harden the platform for production use — performance optimization, error handling audit, accessibility, mobile responsiveness, API rate limiting, monitoring, experimental features page, and documentation. This is the final stage before launch, ensuring the platform is fast, reliable, accessible, and well-documented.

**Spec Reference:** §48

---

#### US-28.1: Performance Optimization

**As a** musician, **I want** the platform to load quickly and respond instantly, **so that** I can focus on creating music without waiting for the interface.

**Description:**
Audit and optimize all critical performance paths — lazy loading for heavy components, CDN caching for images and audio, API response time targets, and efficient data fetching patterns.

**Functional Requirements:**
- Lazy loading for: waveform components, studio editor, video player, heavy library views
- Image and audio assets served via CDN with appropriate cache headers
- API response time target: <200ms for reads, <500ms for writes (excluding generation jobs)
- Bundle size audit: code-split routes, tree-shake unused dependencies
- Database query optimization: add indexes for common query patterns
- Audio streaming: progressive loading for long clips (not full download before playback)

**Acceptance Criteria:**
- [ ] Initial page load (Time to Interactive) under 3 seconds on broadband
- [ ] API read endpoints respond in under 200ms (p95)
- [ ] Navigating between pages does not trigger full-page reloads
- [ ] Audio playback begins within 1 second of clicking play (not after full download)
- [ ] Lighthouse performance score above 80 for key pages

---

#### US-28.2: Error Handling and User Experience Audit

**As a** musician, **I want** every error to show a helpful, human-readable message, **so that** I never see a raw stack trace or cryptic error code.

**Description:**
Audit all error paths across the frontend and API. Replace raw error messages, stack traces, and generic "Something went wrong" messages with specific, actionable guidance.

**Functional Requirements:**
- Frontend error boundary catches all unhandled exceptions and shows a recovery UI
- API errors return consistent format: `{ error: string, code: string, details?: string, action?: string }`
- No raw stack traces exposed to users in any environment (including 500 errors)
- Network errors show "Connection lost — retrying" with automatic retry
- Generation failures show specific guidance (e.g., "Server busy — try again in 30 seconds")
- Form validation errors appear inline next to the relevant field
- 404 pages have navigation back to home and search

**Acceptance Criteria:**
- [ ] No endpoint returns raw stack traces in production (verified by fuzzing)
- [ ] Network disconnection shows a non-blocking retry banner
- [ ] All form validation errors appear inline
- [ ] 500 errors show a user-friendly message with a support link
- [ ] 404 page includes navigation to home and search

---

#### US-28.3: Accessibility

**As a** musician, **I want** the platform to be fully accessible via keyboard and screen reader, **so that** I can use it regardless of my abilities.

**Description:**
Implement WCAG 2.1 AA compliance across all pages — keyboard navigation, screen reader support, ARIA labels, sufficient color contrast, and focus management.

**Functional Requirements:**
- All interactive elements reachable and operable via keyboard (Tab, Enter, Escape, Arrow keys)
- ARIA labels on all non-text interactive elements (buttons, sliders, toggles, icons)
- Focus management: focus moves logically through modals, drawers, and dynamic content
- Color contrast: minimum 4.5:1 for normal text, 3:1 for large text (WCAG AA)
- Audio player controls fully accessible (play, pause, seek, volume)
- Screen reader announces: page transitions, loading states, error messages, generation progress
- Skip-to-content link on every page

**Acceptance Criteria:**
- [ ] All pages pass axe-core automated accessibility audit with zero critical violations
- [ ] A screen reader user can navigate from login through song creation and playback
- [ ] Tab order is logical on all pages (no focus traps except modals)
- [ ] Color contrast meets WCAG AA on all text elements
- [ ] Audio player is fully operable via keyboard

---

#### US-28.4: Mobile Responsiveness and API Rate Limiting

**As a** musician, **I want** the platform to work on my phone and be protected from abuse, **so that** I can create on mobile and trust the platform is stable.

**Description:**
Ensure all pages are usable on mobile viewports (360px–768px) and implement per-user, per-endpoint API rate limiting to prevent abuse and ensure fair resource distribution.

**Functional Requirements:**
- All pages responsive at 360px, 414px, and 768px viewports
- Touch targets minimum 44x44px
- Mobile-optimized navigation: bottom nav bar or hamburger menu
- Audio player adapts to mobile layout (compact mode)
- API rate limiting: per-user, per-endpoint limits (e.g., 60 requests/min for reads, 10/min for generation)
- Rate limit exceeded returns 429 with `Retry-After` header
- Rate limits are tiered by subscription (Pro gets higher limits)
- Rate limit dashboard for admins

**Acceptance Criteria:**
- [ ] All pages render correctly at 360px viewport width
- [ ] Touch targets meet minimum 44x44px size
- [ ] API returns 429 with Retry-After header when rate limit is exceeded
- [ ] Pro users have higher rate limits than Free users
- [ ] Audio player is functional on mobile (play, pause, seek)

---

#### US-28.5: Monitoring, Experimental Features, and Documentation

**As a** developer, **I want** production observability, a feature flag system for experiments, and comprehensive documentation, **so that** we can monitor the platform, test new features safely, and onboard new contributors.

**Description:**
Set up structured logging, error tracking, uptime monitoring, a `/labs` page for experimental features behind feature flags, and auto-generated API documentation. This is the capstone of production readiness.

**Functional Requirements:**
- Structured logging: JSON-formatted logs with request IDs, user IDs, timestamps, and severity levels
- Error tracking: Sentry (or similar) integration for frontend and backend exceptions
- Uptime monitoring: health check endpoint polled every 60 seconds with alerting on downtime
- Experimental features page (`/labs`) with feature flags for: Real-time generation (Alpha), Collaborative workspaces (Alpha), AI Arrangement (Beta), Style Transfer (Beta)
- Feature flags controlled via admin panel (per-user or global rollout)
- API documentation: auto-generated Swagger/OpenAPI docs at `/docs`
- User guide: in-app help pages covering core workflows
- Deployment guide: documented deployment process for VPS

**Acceptance Criteria:**
- [ ] Logs are structured JSON and include request IDs for tracing
- [ ] Sentry captures frontend and backend errors with source maps
- [ ] Uptime monitor alerts when the health endpoint is unreachable for >2 minutes
- [ ] `/labs` page shows experimental features with Alpha/Beta badges and toggle switches
- [ ] Feature flags can be enabled/disabled per user from the admin panel
- [ ] `/docs` serves auto-generated OpenAPI documentation
- [ ] Deployment guide enables a new developer to deploy the platform from scratch

---

**Stage 28 Completion Criteria:**
- Lighthouse performance score above 80 on key pages
- Zero critical accessibility violations
- All pages responsive on mobile viewports
- API rate limiting is active and tested
- Structured logging and error tracking are operational
- `/labs` page is live with feature flags
- API docs are auto-generated and current
- No raw stack traces or cryptic errors exposed to users

---

