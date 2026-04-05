## Layer 3: Web UI

*Goal: Build a Next.js frontend that consumes the Platform API, providing the full creative, social, and distribution experience through the browser. The UI follows the Nova template design system with gray color scheme, Hugeicons, and Nunito Sans typography.*

---

### Stage 15: App Shell & Auth UI

**Overview:** Stand up the Next.js application with the core layout chrome — sidebar navigation, main content area, contextual right panel, and persistent bottom playbar. Add OAuth authentication, profile settings, and the global audio player. After this stage, a musician can log in, configure their profile, and play audio across any page.

---

#### US-15.1: Next.js Project Scaffold

**As a** developer, **I want** a Next.js project initialized with the Nova template (gray scheme, Hugeicons, Nunito Sans), **so that** I have a consistent, accessible design system from the first page.

**Description:**
Bootstrap the `web/` directory using the Nova template with Shadcn/UI and Tailwind CSS. Configure the gray color palette, Hugeicons icon library, and Nunito Sans font. Ensure the dev server runs and renders a placeholder page.

**Functional Requirements:**
- Next.js project created via Nova template setup command with gray base color, Hugeicons, and Nunito Sans
- Tailwind CSS configured with the gray palette and Nova design tokens
- `@hugeicons/react` installed and verified with a sample icon render
- Nunito Sans loaded from Google Fonts with CSS variables
- Dev server starts without errors (`npm run dev`)
- Placeholder index page renders with correct font, color scheme, and a sample icon

**Acceptance Criteria:**
- [ ] `npm run dev` starts the dev server without errors
- [ ] Index page renders with Nunito Sans font applied
- [ ] Gray color palette is active (not zinc or slate)
- [ ] A Hugeicons icon renders correctly on the placeholder page
- [ ] Shadcn/UI components use Nova styling (data-slot attributes, ring-[3px] focus states)

---

#### US-15.2: Application Shell Layout

**As a** musician, **I want** a consistent layout with sidebar navigation, main content, a contextual right panel, and a bottom playbar, **so that** I can navigate the platform without losing context or audio playback.

**Description:**
Build the two-panel layout described in spec section 1.1. The left sidebar is a collapsed icon bar by default, the main content area is route-driven, the right panel shows contextual information, and the bottom playbar persists across all routes.

**Functional Requirements:**
- Left sidebar renders as a collapsed icon bar (icons only, no labels by default)
- Main content area fills remaining horizontal space and is route-driven
- Right panel renders conditionally based on route context (placeholder for now)
- Bottom playbar is fixed at the bottom, visible on all pages
- Layout is responsive: sidebar collapses to icons on smaller screens, right panel hides below a breakpoint
- All panels maintain proper z-index layering

**Acceptance Criteria:**
- [ ] Layout renders with sidebar, main content, and bottom playbar on all routes
- [ ] Right panel is visible on routes that provide contextual content
- [ ] Sidebar does not overlap main content
- [ ] Bottom playbar remains visible during scroll
- [ ] Layout is usable at 1024px, 1440px, and 1920px viewport widths

---

#### US-15.3: Sidebar Navigation

**As a** musician, **I want** icon-based navigation in the sidebar with all major destinations, **so that** I can reach any area of the platform in one click.

**Description:**
Implement the sidebar navigation icons from spec section 1.2 — Home, Explore, Create, Studio, Library, Search, Feed, Notifications, Mastering/Distribution, Labs, and Account. Include the expand/collapse toggle (spec section 1.3) and profile avatar menu (spec section 1.4).

**Functional Requirements:**
- Sidebar icons for all destinations: Home (`/`), Explore (`/explore`), Create (`/create`), Studio (`/studio`), Library (`/me`), Search (`/search`), Feed (`/feed`), Notifications (`/notifications`), Mastering & Distribution (`/release`), Labs (`/labs`), Account (dialog)
- Active route icon is visually highlighted
- Expand/collapse toggle at the top switches between icon-only and full-label mode
- Expanded mode shows icon + text label for each destination
- Profile avatar button at the top opens a dropdown: profile link, account settings, subscription, logout
- Labs and Account icons pinned to the bottom of the sidebar
- All icons sourced from `@hugeicons/react`

**Acceptance Criteria:**
- [ ] All navigation icons render and link to correct routes
- [ ] Active route icon is visually distinct
- [ ] Expand toggle switches sidebar between icon-only and icon+label modes
- [ ] Sidebar state persists across navigation (does not reset on route change)
- [ ] Profile dropdown shows profile, account settings, subscription, and logout options

---

#### US-15.4: OAuth Login and Signup

**As a** musician, **I want** to log in with Google or Discord, **so that** I can start creating music without managing another password.

**Description:**
Implement OAuth/SSO authentication with Google and Discord identity providers. Login redirects to the Create page on success. Unauthenticated users are redirected to the login page when accessing protected routes.

**Functional Requirements:**
- Login page with Google and Discord OAuth buttons
- Optional email/password signup as a fallback
- Successful login redirects to `/create`
- Auth state stored securely (JWT or session cookie)
- Protected routes redirect unauthenticated users to login
- Logout clears session and redirects to login page
- Loading state while OAuth flow is in progress

**Acceptance Criteria:**
- [ ] Google OAuth login completes and redirects to `/create`
- [ ] Discord OAuth login completes and redirects to `/create`
- [ ] Unauthenticated access to `/create` redirects to login
- [ ] Logout clears session and returns to login page
- [ ] Auth tokens are stored securely (httpOnly cookie or equivalent)

---

#### US-15.5: Profile Settings Page

**As a** musician, **I want** to set my display name, handle, avatar, bio, and style tags, **so that** my public profile reflects who I am as a creator.

**Description:**
Build the profile settings page where users configure their identity. This data is displayed on the public profile page (`/@username`) and used by the personalization engine for style recommendations.

**Functional Requirements:**
- Display name text input
- Username handle input (`@username`) with availability check
- Avatar image upload (drag-and-drop or file picker, crop to square)
- Bio/description textarea (character limit displayed)
- Style tags as pill badges (add/remove, typeahead suggestions, e.g., "cello," "orchestral," "lo-fi")
- Save button with loading state and success/error feedback
- Form validation: handle must be unique, avatar must be an image, style tags have a reasonable max count

**Acceptance Criteria:**
- [ ] All fields save successfully and persist on page reload
- [ ] Username handle shows real-time availability feedback
- [ ] Avatar upload previews the image before saving
- [ ] Style tags render as removable pill badges
- [ ] Validation errors display inline next to the offending field

---

#### US-15.6: Global Audio Player

**As a** musician, **I want** a persistent player at the bottom of every page with full playback controls, **so that** I can listen to any clip while navigating the platform.

**Description:**
Implement the global playbar described in spec section 46. The player supports play/pause, previous/next, progress scrubbing, volume control, waveform visualization, song info display, queue management, repeat/shuffle modes, and a like button. Audio playback continues uninterrupted across route transitions.

**Functional Requirements:**
- Play/pause toggle
- Previous/next track buttons
- Progress scrubber (click or drag to seek)
- Current time and total duration display
- Volume slider with mute toggle
- Waveform visualization (miniature waveform in the playbar)
- Song info display: thumbnail, title, artist
- Queue button (opens queue panel showing upcoming tracks)
- Repeat mode toggle (off / repeat-all / repeat-one)
- Shuffle toggle
- Like button (heart icon, toggles liked state)
- Audio continues playing across route changes (no interruption on navigation)
- Keyboard shortcuts: space (play/pause), left/right arrows (seek), up/down arrows (volume)

**Acceptance Criteria:**
- [ ] Play/pause, prev/next, and scrubber work correctly
- [ ] Audio continues playing when navigating between routes
- [ ] Volume slider and mute toggle control audio level
- [ ] Queue panel displays upcoming tracks and allows reordering
- [ ] Repeat and shuffle modes function correctly
- [ ] Song info (thumbnail, title, artist) updates when track changes
- [ ] Keyboard shortcuts work when player is active

---

**Stage 15 Completion Criteria:**
- Next.js project runs with Nova template styling (gray palette, Hugeicons, Nunito Sans)
- App shell layout renders correctly at multiple viewport widths
- All sidebar navigation links route to the correct pages
- OAuth login with Google and Discord works end-to-end
- Profile settings save and persist
- Global player plays audio across all routes without interruption
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 16: Creation Pages

**Overview:** Build the song creation UI — the heart of the platform. Implement Simple, Advanced, and Sounds creation modes, the model/version selector, the workspace clip panel, clip cards with full actions, and audio input modals. After this stage, a musician can compose songs through the browser with the same power as the CLI.

---

#### US-16.1: Simple Creation Mode

**As a** musician, **I want** a minimal creation form where I describe a song in plain language, **so that** I can generate music quickly without configuring parameters.

**Description:**
Build the Simple tab on the `/create` page with the song description textarea, instrumental toggle, +Audio button, +Lyrics button, and AI-suggested inspiration tags with a shuffle button. This is the low-barrier entry point for music creation.

**Functional Requirements:**
- Song description textarea with placeholder text (e.g., "Describe the song you want to create...")
- Instrumental toggle (boolean switch to suppress vocals)
- "+Audio" button opens the audio input modal (US-16.7)
- "+Lyrics" button opens an inline lyrics entry field
- Inspiration tags: AI-suggested style tag pills rendered below the description
- Each tag is clickable to add it to the generation context
- Shuffle button randomizes/refreshes the tag suggestions
- Create button at the bottom (disabled until at least one field is populated)

**Acceptance Criteria:**
- [ ] Description textarea accepts free-form text input
- [ ] Instrumental toggle visibly changes state and is sent with generation request
- [ ] Inspiration tags render as clickable pills; clicking adds the tag to the form context
- [ ] Shuffle button replaces current tag suggestions with new ones
- [ ] Create button is disabled when all fields are empty
- [ ] Create button is enabled when description or lyrics are provided

---

#### US-16.2: Advanced Creation Mode

**As a** musician, **I want** separate controls for lyrics, styles, and generation parameters, **so that** I have precise creative control over every aspect of the song.

**Description:**
Build the Advanced tab with the lyrics panel (textarea, enhance, undo, save, clear, manual/auto toggle), styles panel (textarea, magic wand, tag pills, shuffle, undo, save, clear), and the expandable "More Options" section containing all parameters from spec section 4.4.

**Functional Requirements:**
- Lyrics panel: textarea with structure tag support (`[Verse]`, `[Chorus]`, etc.), vocal language dropdown, enhance input field, undo, save preset, clear, and manual/auto toggle
- Styles panel: comma-separated styles textarea, personalized magic wand button, clickable style tag pills, shuffle, undo, save preset, clear
- More Options (collapsed by default): exclude styles, vocal gender toggle, lyrics mode, BPM (60-180 or Auto), key selector, time signature selector, duration input, weirdness slider (0-100), style influence slider (0-100), song title, save to workspace selector, seed input
- All controls send their values to the generation API
- Undo buttons revert to previous state for their respective fields

**Acceptance Criteria:**
- [ ] Lyrics panel supports structured sections and vocal language selection
- [ ] Enhance lyrics input triggers AI rewrite of the lyrics field
- [ ] Styles textarea and tag pills both contribute to the style string
- [ ] More Options section expands/collapses and exposes all generation parameters
- [ ] BPM, key, duration, weirdness, and style influence values are validated before submission
- [ ] Undo buttons revert their respective fields to the previous state

---

#### US-16.3: Sounds Creation Mode

**As a** musician, **I want** to generate short audio samples like loops and one-shots, **so that** I can create building blocks for my productions.

**Description:**
Build the Sounds tab with a description textarea, type selector (one-shot or loop), BPM input, and key selector. Outputs are short clips stored in the workspace alongside songs.

**Functional Requirements:**
- Sound description textarea
- Type selector: One-Shot or Loop (required)
- BPM numeric input (or "Auto") for loops
- Key selector ("Any" or specific musical key)
- Create button behavior matches Simple/Advanced mode (disabled until valid, 2 clips generated)
- Generated clips tagged as sounds in the workspace

**Acceptance Criteria:**
- [ ] Type selector is required before Create is enabled
- [ ] BPM and key fields are available and sent with the request
- [ ] Generated sound clips appear in the workspace panel with correct metadata
- [ ] Loop clips include tempo metadata

---

#### US-16.4: Model and Version Selector

**As a** musician, **I want** to choose which AI model generates my music, **so that** I can trade off between speed and quality.

**Description:**
Add a model/version selector dropdown accessible from all creation modes. Shows available model variants with descriptions, VRAM info, and subscription requirements.

**Functional Requirements:**
- Version badge button visible on all creation tabs
- Dropdown lists: Create Custom Model (Beta), Latest Model (XL), Standard Model, Turbo Model, Legacy Models
- Each option shows name, brief description, and Pro badge if subscription required
- Selected model persists across tab switches within the same session
- Default model configurable in user settings

**Acceptance Criteria:**
- [ ] Model selector is accessible from Simple, Advanced, and Sounds tabs
- [ ] Selecting a model updates the generation request payload
- [ ] Pro-only models show a badge or lock indicator for free-tier users
- [ ] Selected model persists when switching between creation tabs

---

#### US-16.5: Workspace and Clip Library Panel

**As a** musician, **I want** a workspace panel showing all my clips with search, filters, and sorting, **so that** I can manage my generated content alongside creation.

**Description:**
Build the right-side workspace panel on the Create page with clip cards in list view, workspace breadcrumb, search, filter controls, sort dropdown, and pagination. This panel is the musician's clip library during the creation workflow.

**Functional Requirements:**
- Workspace breadcrumb showing current workspace path (clickable to navigate)
- Search input filtering clips by title or metadata
- Filters button with active filter count badge; filter panel includes: liked, public, uploads
- Sort dropdown: Newest, Oldest
- Pagination controls (previous/next + page number)
- Clip cards rendered in list view (see US-16.6)
- Panel scrolls independently of main content

**Acceptance Criteria:**
- [ ] Workspace breadcrumb displays current workspace and navigates on click
- [ ] Search filters clips in real time by title or metadata
- [ ] Filter toggles (Liked, Public, Uploads) narrow the clip list
- [ ] Sort dropdown reorders clips
- [ ] Pagination loads additional pages of clips
- [ ] Panel scrolls independently from the creation form

---

#### US-16.6: Clip Card Component

**As a** musician, **I want** each clip card to show its metadata, playback controls, and quick actions, **so that** I can preview, edit, and manage clips without leaving the creation page.

**Description:**
Build the clip card component for the workspace list view. Each card displays thumbnail, title (inline editable), version badge, metadata badge, style description, and action buttons. This component is reused across the workspace panel, library, and search results.

**Functional Requirements:**
- Thumbnail with duration overlay and play button (plays clip in global player)
- Title with inline edit (pencil icon, click to rename)
- Version badge (model that generated the clip)
- Metadata badge (Cover, Upload, Studio, Extend 1, Mastered, etc.)
- Style description (truncated with tooltip for full text)
- Like / Dislike / Share action buttons
- Publish button (toggles public visibility)
- "Get Full Song" button (visible on short clips under ~60 seconds)
- Remix/Edit button (primary CTA with dropdown arrow for sub-options)
- More options menu (three-dot icon) with full action list from spec section 9.2

**Acceptance Criteria:**
- [ ] Clip card renders all metadata fields correctly
- [ ] Play button sends the clip to the global player
- [ ] Inline title edit saves on blur or Enter key
- [ ] Like/dislike/share/publish buttons trigger appropriate API calls
- [ ] More options menu renders all actions from spec section 9.2
- [ ] "Get Full Song" button is only visible on clips shorter than ~60 seconds

---

#### US-16.7: Create Button Behavior and Generation Flow

**As a** musician, **I want** the Create button to show progress and deliver clips to my workspace, **so that** I have clear feedback during generation and immediate access to results.

**Description:**
Wire the Create button across all modes to submit the form to the generation API. Show a progress indicator during generation, display generation time estimates based on the selected model, and render 2 new clip cards in the workspace panel when complete.

**Functional Requirements:**
- Create button disabled until minimum inputs are satisfied
- On click: button shows a progress indicator (spinner or progress bar)
- Generation time estimate displayed based on selected model (Turbo: ~2-5s, Standard: ~10-30s, XL: ~30-60s)
- On success: 2 new clip cards appear at the top of the workspace panel
- On failure: error state with message and retry option
- Each generation consumes credits (credit count updates in UI)
- "Clear all" button resets all form inputs to defaults

**Acceptance Criteria:**
- [ ] Create button is disabled when form is empty and enabled when valid
- [ ] Progress indicator is visible during generation
- [ ] Generation time estimate reflects the selected model
- [ ] 2 new clip cards appear in the workspace panel on success
- [ ] Error state shows a meaningful message with retry option
- [ ] "Clear all" resets all fields across the active tab

---

#### US-16.8: Audio Input Modals

**As a** musician, **I want** to attach audio references, custom voices, and playlist inspiration to my generation, **so that** the AI has richer context to work with.

**Description:**
Build the three audio input modals: Add Audio (remix from workspace/upload from disk/record from mic), Add Voice (select a custom voice model), and Add Inspiration (reference a playlist). These are accessible from both Simple and Advanced creation modes.

**Functional Requirements:**
- Add Audio modal with three sub-tabs:
  - Remix: search and select a clip from workspace or public songs
  - Upload: drag-and-drop or file picker for local audio (WAV, FLAC, MP3, OGG, AAC, AIFF)
  - Record: browser microphone recording with start/stop/preview controls
- Add Voice modal: list of user's custom voice models with preview playback, select one
- Add Inspiration modal: list of user's playlists, select one as inspirational context
- Selected inputs display as removable chips/badges on the creation form
- Each input is sent as part of the generation API request

**Acceptance Criteria:**
- [ ] Add Audio modal opens with Remix, Upload, and Record tabs
- [ ] Uploading a file shows a preview and attaches it to the form
- [ ] Recording audio works via browser microphone API
- [ ] Add Voice modal lists available voice models
- [ ] Add Inspiration modal lists user's playlists
- [ ] Selected inputs appear as removable badges on the creation form

---

**Stage 16 Completion Criteria:**
- All three creation modes (Simple, Advanced, Sounds) are functional
- Model selector is accessible and affects generation requests
- Workspace panel displays clips with full search, filter, sort, and pagination
- Clip cards render all metadata and actions correctly
- Create button submits to the API and delivers results to the workspace
- Audio input modals (Add Audio, Add Voice, Add Inspiration) work end-to-end
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 17: Song Detail & Editing UI

**Overview:** Build the song detail page and the editing workflow modals that let musicians refine their compositions. This includes the full waveform player, metadata display, action menus, editing operations (extend, cover, remix, mashup, sample, replace, crop, speed, add vocal, remaster), the "Get Full Song" assembly flow, clip context menus, and generation lineage visualization. After this stage, the browser experience matches the full editing power of the CLI.

---

#### US-17.1: Song Detail Page

**As a** musician, **I want** a dedicated page for each song showing its waveform player, metadata, lyrics, lineage, and comments, **so that** I can review and share my work in full detail.

**Description:**
Build the song detail page at `/song/:id` with all content described in spec section 23: full waveform player with scrubber, song metadata (model, BPM, key, duration, created date, mastering status, distribution status), lyrics display, generation lineage, comments section, related songs panel, and full action menu.

**Functional Requirements:**
- Full waveform player with click-to-seek scrubber
- Metadata display: model version, BPM, key, duration, created timestamp, mastering status, distribution status
- Song title, artist name, and style tags prominently displayed
- Lyrics section (scrollable, synchronized if available)
- Like / Dislike / Share / Publish inline controls
- Comments section (visible for public songs)
- Related/similar songs panel (right side or below)
- Full action menu accessible from a primary button

**Acceptance Criteria:**
- [ ] Song detail page loads at `/song/:id` with correct song data
- [ ] Waveform player renders and supports click-to-seek
- [ ] All metadata fields display correctly
- [ ] Lyrics section renders with structure tags formatted
- [ ] Like/dislike/share/publish actions work inline
- [ ] Related songs panel shows relevant suggestions

---

#### US-17.2: Full Action Menu

**As a** musician, **I want** access to all edit, remix, and export operations from the song detail page, **so that** I can perform any action on a song without navigating elsewhere.

**Description:**
Implement the full action menu combining clip card actions and song-level operations. This is the central hub for all operations a musician can perform on a song.

**Functional Requirements:**
- Menu accessible from a primary action button on the song detail page
- Actions grouped by category:
  - Edit: Remix, Edit (Repaint), Open in Editor, Open in Studio
  - Create: Cover, Extend, Mashup, Sample from Song, Use as Inspiration
  - Audio: Add Vocal, Remaster, Replace Section, Crop, Adjust Speed
  - Export: Send to Mastering, Export to DAW, Create Music Video, Download (MP3/WAV/FLAC/Stems)
  - Manage: Publish/Unpublish, Delete
- Each action opens the appropriate modal, panel, or navigates to the relevant page
- Pro-only actions show a badge for free-tier users

**Acceptance Criteria:**
- [ ] Action menu renders all operations grouped by category
- [ ] Each action triggers the correct workflow (modal, navigation, or inline)
- [ ] Pro-only actions are visually distinguished for free-tier users
- [ ] Menu is keyboard navigable and accessible

---

#### US-17.3: Editing Workflow Modals

**As a** musician, **I want** modal-based editing workflows for extend, cover, remix, mashup, sample, replace section, crop, speed adjust, add vocal, and remaster, **so that** I can refine my songs through the browser.

**Description:**
Build modal or panel-based UIs for each editing workflow from spec sections 10-19. Each modal presents the relevant controls, submits to the API, and delivers results to the workspace.

**Functional Requirements:**
- Extend modal: extension point selector (end or timestamp), duration, style override, lyrics continuation
- Cover modal: target style input, voice model selector, lyrics override
- Remix modal: new style descriptors, parameter overrides
- Mashup modal: multi-clip selector (2+), blend mode (layered/sequential/AI-guided), style override
- Sample from Song modal: waveform range selector, sample role picker, generation prompt
- Replace Section modal: waveform range selector, replacement instructions, lock-context toggle
- Crop modal: waveform range selector, snap-to-beat toggle, fade-in/fade-out controls
- Adjust Speed modal: speed multiplier slider (0.5x-2.0x), preserve pitch toggle, target BPM input
- Add Vocal modal: lyrics input, voice model selector, vocal style descriptors
- Remaster: one-click action (no modal, shows progress indicator)
- All modals show a progress state during processing and deliver results to the workspace

**Acceptance Criteria:**
- [ ] Each editing modal opens with the correct controls for its workflow
- [ ] Form validation prevents invalid submissions (e.g., empty required fields)
- [ ] Submitting a modal triggers the correct API endpoint
- [ ] Results appear as new clips in the workspace upon completion
- [ ] Remaster triggers immediately without a modal and shows progress

---

#### US-17.4: Get Full Song Flow

**As a** musician, **I want** to automatically extend a short clip into a full-length song with section-by-section review, **so that** I can build a complete composition from a seed idea.

**Description:**
Implement the "Get Full Song" flow from spec section 21. The system plans a song structure, executes sequential extends, and presents each section for review before continuing.

**Functional Requirements:**
- Triggered from clip cards (clips under ~60 seconds) or song detail page
- Displays planned song structure (intro, verse, chorus, verse, chorus, bridge, outro)
- Generates sections sequentially with progress indication
- After each section: preview playback, accept or reject
- Rejected sections can be regenerated with modified instructions
- Final assembly produces a single clip containing all accepted sections
- Target duration: ~3-4 minutes (configurable)

**Acceptance Criteria:**
- [ ] Flow is available on clips shorter than ~60 seconds
- [ ] Planned structure is displayed before generation begins
- [ ] Each section can be previewed, accepted, or rejected
- [ ] Rejected sections can be regenerated with new instructions
- [ ] Final assembled clip appears in the workspace

---

#### US-17.5: Clip Context Menu

**As a** musician, **I want** a context menu on every clip with all available actions including mastering, DAW export, video, and download options, **so that** I can perform any operation from wherever a clip appears.

**Description:**
Build the three-dot (more options) context menu for clip cards with the full action list from spec section 9.2. This menu is reused across the workspace panel, library, search results, and any other location where clip cards appear.

**Functional Requirements:**
- Three-dot icon button opens a dropdown menu
- Menu items: Remix/Edit, Open in Studio, Open in Editor (Pro), Cover, Extend, Mashup, Sample from Song (Beta), Use as Inspiration, Send to Mastering, Export to DAW, Create Music Video, Download submenu (MP3/WAV/FLAC/Stems), Delete
- Download submenu expands on hover/click
- Delete requires confirmation dialog
- Menu items trigger appropriate modals, navigation, or API calls
- Context-sensitive: some items hidden based on clip state (e.g., no "Get Full Song" on long clips)

**Acceptance Criteria:**
- [ ] Context menu renders all action items from spec section 9.2
- [ ] Download submenu expands to show format options
- [ ] Delete shows a confirmation dialog before proceeding
- [ ] Menu items correctly trigger their respective workflows
- [ ] Context menu renders consistently across all clip card locations

---

#### US-17.6: Like, Dislike, Share, and Publish Actions

**As a** musician, **I want** inline like, dislike, share, and publish controls on clips and song detail pages, **so that** I can engage with content and control visibility without extra steps.

**Description:**
Implement inline action buttons that appear on clip cards and song detail pages. These are the primary engagement and visibility controls.

**Functional Requirements:**
- Like button (heart icon): toggles liked state, updates count, persists to API
- Dislike button: toggles dislike state, affects recommendations
- Share button: opens share modal with copy-link, and social sharing options
- Publish button: toggles between private/unlisted/public visibility states
- Publishing requires a title and at least one style tag; prompt if missing
- Optimistic UI updates with rollback on API failure

**Acceptance Criteria:**
- [ ] Like/dislike toggle states correctly and persist after page reload
- [ ] Share modal provides a copyable link
- [ ] Publish toggle changes visibility state with API confirmation
- [ ] Publishing without a title or style tag shows a prompt to add them
- [ ] UI updates optimistically and rolls back on error

---

#### US-17.7: Generation Lineage Visualization

**As a** musician, **I want** to see the generation history of a clip showing its parent clips, **so that** I can trace how a song evolved through remixes, extends, and covers.

**Description:**
Display the generation lineage on the song detail page. Show parent clips (the clips this song was derived from) as a visual chain or tree, with clickable links to each ancestor.

**Functional Requirements:**
- Lineage section on the song detail page
- Shows parent clip(s) with thumbnails, titles, and relationship labels (e.g., "Remixed from," "Extended from," "Cover of")
- Each parent is clickable, navigating to its song detail page
- For multi-parent operations (mashup): show all source clips
- Visual representation as a horizontal chain or simple tree

**Acceptance Criteria:**
- [ ] Lineage section displays parent clips with correct relationship labels
- [ ] Clicking a parent navigates to that clip's song detail page
- [ ] Mashup clips show multiple parents
- [ ] Clips with no parents (original generations) show "Original" or omit the section

---

**Stage 17 Completion Criteria:**
- Song detail page renders all metadata, lyrics, waveform player, and actions
- All editing workflow modals are functional and submit to the API
- "Get Full Song" flow supports section-by-section review
- Clip context menus provide access to all spec section 9.2 actions
- Like/dislike/share/publish inline actions work across all clip locations
- Generation lineage is displayed and navigable
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 18: Waveform Editor UI

**Overview:** Build the in-browser waveform-level audio editor for precise clip manipulation. This is the "Open in Editor" Pro feature from spec section 22. The editor provides zoom, region selection, cut/copy/paste, fades, gain tools, undo/redo, and repaint mode integration. All edits are non-destructive — they create new clip versions.

---

#### US-18.1: Waveform Display with Zoom and Scroll

**As a** musician, **I want** a full waveform display with zoom and scroll controls, **so that** I can see and navigate the audio at any level of detail.

**Description:**
Render the clip's audio waveform in a scrollable, zoomable canvas. The waveform is the foundation of all editor interactions — region selection, editing operations, and repaint mode all depend on accurate waveform rendering.

**Functional Requirements:**
- Full waveform rendered from the clip's audio data
- Horizontal zoom: zoom in/out via scroll wheel, pinch gesture, or +/- buttons
- Zoom range from full-clip overview to sample-level detail
- Horizontal scroll when zoomed in (scroll bar and drag)
- Playhead indicator showing current playback position
- Time ruler above the waveform (mm:ss or bars+beats)
- Click on waveform sets the playhead position
- Responsive: fills available width of the editor panel

**Acceptance Criteria:**
- [ ] Waveform renders accurately for the loaded clip
- [ ] Zoom in/out works smoothly with visible detail change
- [ ] Scrolling navigates through a zoomed-in waveform
- [ ] Playhead moves during playback and can be repositioned by clicking
- [ ] Time ruler labels update correctly at different zoom levels

---

#### US-18.2: Region Selection and Clipboard Operations

**As a** musician, **I want** to select a time range and perform cut, copy, paste, and delete operations, **so that** I can rearrange and restructure audio precisely.

**Description:**
Click-and-drag on the waveform to select a time range. Selected regions can be cut, copied, pasted at the playhead, or deleted. These are the fundamental editing primitives.

**Functional Requirements:**
- Click-and-drag on the waveform creates a highlighted region selection
- Selection handles at start/end for fine adjustment
- Keyboard shortcuts: Ctrl+X (cut), Ctrl+C (copy), Ctrl+V (paste at playhead), Delete (delete region)
- Cut: removes selected audio, shifts remaining audio left
- Copy: copies selected audio to clipboard (in-app, not system clipboard)
- Paste: inserts clipboard audio at the current playhead position
- Delete: removes selected audio, shifts remaining audio left (same as cut without copy)
- Selection info display: start time, end time, duration

**Acceptance Criteria:**
- [ ] Click-and-drag creates a visible selection region
- [ ] Selection handles allow fine-tuning start and end points
- [ ] Cut removes audio and shortens the clip
- [ ] Copy + paste duplicates audio at the playhead position
- [ ] Delete removes selected audio
- [ ] Keyboard shortcuts work correctly

---

#### US-18.3: Fades and Gain Tools

**As a** musician, **I want** to apply fade-in, fade-out, crossfade, normalize, silence, and gain adjustments, **so that** I can polish transitions and levels within a clip.

**Description:**
Provide toolbar tools for common audio processing operations on selected regions or the entire clip. These are non-destructive and preview in real time.

**Functional Requirements:**
- Fade-in: applies a linear or logarithmic fade to the start of a selection
- Fade-out: applies a fade to the end of a selection
- Crossfade: blends two adjacent regions with configurable overlap duration
- Normalize: scales audio to peak at 0 dB (or a specified level)
- Silence: replaces selected region with silence
- Gain adjustment: slider or numeric input to raise/lower volume of selection (in dB)
- Real-time preview of gain changes before applying
- All tools accessible from a toolbar above the waveform

**Acceptance Criteria:**
- [ ] Fade-in and fade-out are audible in the affected region
- [ ] Crossfade creates a smooth transition between adjacent regions
- [ ] Normalize adjusts peak level to the target
- [ ] Silence replaces the selection with zero audio
- [ ] Gain adjustment changes volume by the specified dB amount
- [ ] All tools are accessible from the editor toolbar

---

#### US-18.4: Undo/Redo and Non-Destructive Editing

**As a** musician, **I want** unlimited undo/redo and non-destructive editing, **so that** I can experiment freely without fear of losing my work.

**Description:**
Maintain an undo/redo stack for all editor operations. Every edit creates a new version — the original clip is never modified. The musician can revert any number of steps or save the current state as a new clip version.

**Functional Requirements:**
- Unlimited undo/redo stack (persists for the editing session)
- Keyboard shortcuts: Ctrl+Z (undo), Ctrl+Shift+Z (redo)
- Undo/redo buttons in the toolbar with disabled state when at stack boundary
- "Save as new version" button creates a new clip in the workspace
- Original clip is preserved unchanged
- History panel (optional) showing the list of operations performed

**Acceptance Criteria:**
- [ ] Undo reverts the last operation and redo re-applies it
- [ ] Multiple undos walk back through the full operation history
- [ ] "Save as new version" creates a new clip in the workspace with correct lineage
- [ ] Original clip remains unchanged after any number of edits
- [ ] Undo/redo buttons are disabled when at the start/end of the stack

---

#### US-18.5: Repaint Mode Integration

**As a** musician, **I want** to select a range in the editor and regenerate that section with a new prompt, **so that** I can use AI to fix or reimagine specific parts of a clip.

**Description:**
Integrate the Repaint/Edit workflow (spec section 10.2) into the waveform editor. The musician selects a time range, provides new instructions (prompt, style, lyrics), and the AI regenerates only that section while blending seamlessly with surrounding audio.

**Functional Requirements:**
- Select a region in the waveform editor to activate Repaint mode
- Repaint panel appears with: prompt/instructions textarea, style override field, lyrics override field
- "Regenerate" button submits the selected range and instructions to the API
- Progress indicator during regeneration
- Result replaces the selected region in the editor view
- Surrounding audio is unchanged; crossfade applied at boundaries
- Result can be undone (returns to pre-repaint state)
- Save as new version to persist the change

**Acceptance Criteria:**
- [ ] Selecting a region enables the Repaint mode panel
- [ ] Providing instructions and clicking Regenerate submits to the API
- [ ] Regenerated section replaces only the selected range in the waveform
- [ ] Surrounding audio remains intact with smooth transitions
- [ ] Repaint result is undoable
- [ ] Saving creates a new clip version in the workspace

---

**Stage 18 Completion Criteria:**
- Waveform editor renders and supports zoom, scroll, and playback
- Region selection and clipboard operations (cut, copy, paste, delete) work correctly
- Fade, gain, normalize, and silence tools function as specified
- Undo/redo stack supports unlimited operations
- All edits are non-destructive (original clip preserved, new versions created)
- Repaint mode integrates AI regeneration into the editor workflow
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 19: Multi-Track Studio UI

**Overview:** Build the in-browser multi-track DAW at `/studio` — a horizontal timeline with vertically stacked track lanes, per-track controls, a master bus with EQ/compressor/limiter, and export capabilities. After this stage, a musician can arrange, layer, and mix multiple clips into a complete production entirely in the browser.

---

#### US-19.1: Studio Timeline and Track Lanes

**As a** musician, **I want** a horizontal timeline with a time ruler and vertically stacked track lanes, **so that** I can arrange multiple clips visually on a timeline.

**Description:**
Build the core Studio layout at `/studio`: a horizontal timeline with a time ruler (switchable between bars+beats and mm:ss), vertically stacked track lanes, and the ability to drag clips onto tracks. This is the spatial arrangement canvas for multi-track production.

**Functional Requirements:**
- Horizontal time ruler with bars+beats and mm:ss display modes (toggle)
- Vertically stacked track lanes; new tracks can be added
- Clips rendered as colored blocks on track lanes showing title and waveform thumbnail
- Drag-and-drop clips from workspace panel onto track lanes
- Clips can be repositioned by dragging along the timeline
- Horizontal zoom and scroll for the timeline
- Playhead with transport controls (play, pause, stop, return to start)
- Playback renders all tracks mixed together through the global player

**Acceptance Criteria:**
- [ ] Time ruler renders with correct time markings in both display modes
- [ ] Track lanes stack vertically and accept dropped clips
- [ ] Clips render as blocks with title and waveform preview
- [ ] Dragging a clip repositions it on the timeline
- [ ] Playback plays all tracks simultaneously through the global player
- [ ] Zoom and scroll work on the timeline

---

#### US-19.2: Track Types and Clip Import

**As a** musician, **I want** to create different track types (AI-generated, uploaded audio, sounds/loops, vocal stems), **so that** I can organize my arrangement by source material.

**Description:**
Support four track types from spec section 24.2. Each type has a visual indicator and accepts clips of its category. Clips can be imported from the workspace or dragged from the clip library panel.

**Functional Requirements:**
- Track type selector when adding a new track: AI-Generated, Audio, Sound/Loop, Vocal
- Track type indicated by color label and icon
- Clips from the workspace panel can be dragged onto matching track types
- Sounds/loops placed on loop tracks inherit the project tempo
- Multiple clips on the same track arranged sequentially
- Clips on different tracks play simultaneously (layered)

**Acceptance Criteria:**
- [ ] All four track types can be created
- [ ] Each type is visually distinguished by color and icon
- [ ] Clips from the workspace can be dragged onto tracks
- [ ] Multiple clips on one track play sequentially
- [ ] Clips on different tracks play simultaneously

---

#### US-19.3: Snap-to-Grid, Loop Regions, and Markers

**As a** musician, **I want** snap-to-grid, loop regions, and named markers, **so that** my arrangement stays rhythmically precise and organized.

**Description:**
Add timeline interaction features: snap-to-grid quantizes clip placement to beat divisions, loop regions define playback loops, and named markers label song sections.

**Functional Requirements:**
- Snap-to-grid toggle with configurable grid resolution (1 bar, 1 beat, 1/2 beat, 1/4 beat)
- Clip edges snap to the nearest grid line when snapping is enabled
- Loop region: draggable start/end markers on the time ruler defining a loop range
- When loop is active, playback repeats within the loop region
- Named markers: click on ruler to add a marker with a label (e.g., "Verse 1," "Chorus")
- Markers are visually displayed as flags on the time ruler
- Markers can be renamed, moved, or deleted

**Acceptance Criteria:**
- [ ] Snap-to-grid quantizes clip placement to the selected grid resolution
- [ ] Loop region causes playback to repeat within the defined range
- [ ] Named markers render on the time ruler with labels
- [ ] Markers can be added, renamed, moved, and deleted

---

#### US-19.4: Per-Track Controls

**As a** musician, **I want** volume, pan, mute, solo, color, and AI regenerate controls on each track, **so that** I can mix and refine individual elements of my arrangement.

**Description:**
Each track lane has a control strip on the left side with volume fader, pan knob, mute/solo buttons, track color selector, and an AI Regenerate button that re-generates the track's content with modified parameters.

**Functional Requirements:**
- Volume fader (vertical or horizontal slider, range: -inf to +6 dB)
- Pan knob (left-center-right, -100 to +100)
- Mute button: silences the track (visual indicator on muted track)
- Solo button: solos the track (mutes all others; multiple solos allowed)
- Track color selector: choose a color label for visual organization
- AI Regenerate button: opens a prompt dialog to regenerate the track's clip(s) with new parameters
- Track name (editable inline)

**Acceptance Criteria:**
- [ ] Volume fader changes the track's playback level
- [ ] Pan knob shifts the track's stereo position
- [ ] Mute silences the track; solo mutes all non-soloed tracks
- [ ] Track color is selectable and visually applied
- [ ] AI Regenerate opens a prompt and generates a new clip for the track
- [ ] Track name is editable inline

---

#### US-19.5: Master Bus Controls

**As a** musician, **I want** a master bus with volume, EQ, compressor, and limiter, **so that** I can shape the overall mix before exporting.

**Description:**
Build the master bus section with master volume, 3-band EQ (low/mid/high shelf), compressor (threshold, ratio, attack, release), and limiter. These controls affect the summed output of all tracks.

**Functional Requirements:**
- Master volume fader
- 3-band EQ: low shelf, mid peak, high shelf with frequency and gain controls
- Compressor: threshold, ratio, attack, release knobs
- Limiter: ceiling knob
- All controls update the audio output in real time
- Visual metering (peak and RMS levels for left/right channels)

**Acceptance Criteria:**
- [ ] Master volume controls the overall output level
- [ ] EQ bands audibly affect the frequency spectrum
- [ ] Compressor and limiter respond to dynamics as expected
- [ ] Visual metering shows peak and RMS levels in real time

---

#### US-19.6: Studio Export and Handoff

**As a** musician, **I want** to export a mixdown, send to mastering, and export for DAW from the studio, **so that** I can finalize and distribute my multi-track production.

**Description:**
Add export capabilities to the Studio: "Export Mixdown" bounces all tracks to a single file, "Send to Mastering" exports the mixdown and opens the mastering pipeline, and "Export for DAW" exports individual track stems with project metadata.

**Functional Requirements:**
- Export Mixdown: bounces all tracks to a single WAV file (48kHz, 24-bit), saves to workspace
- Send to Mastering button on the master bus: triggers mixdown export, then navigates to `/release` mastering tab with the mixdown pre-selected
- Export for DAW button: exports individual track stems as WAV files + project metadata JSON (tempo, markers, track names), packaged as a ZIP
- Format selection for mixdown: WAV, FLAC, MP3
- Progress indicator during export
- Exported files registered in workspace with "Studio" metadata badge

**Acceptance Criteria:**
- [ ] Export Mixdown produces a single playable audio file
- [ ] Send to Mastering navigates to the mastering page with the mixdown pre-loaded
- [ ] Export for DAW produces a ZIP with stems and metadata JSON
- [ ] Export progress is visible to the user
- [ ] Exported clips appear in the workspace with correct metadata

---

**Stage 19 Completion Criteria:**
- Studio page renders a functional multi-track timeline with drag-and-drop clips
- All four track types are supported
- Snap-to-grid, loop regions, and markers work correctly
- Per-track controls (volume, pan, mute, solo, color, AI regenerate) function as specified
- Master bus provides volume, EQ, compressor, and limiter
- Export mixdown, send to mastering, and DAW export all work
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 20: Discovery & Social UI

**Overview:** Build the discovery, search, playlist, feed, profile, and notification pages that transform the platform from a creation tool into a social music community. After this stage, musicians can explore trending content, find music by genre or attribute, curate playlists, scroll a short-form feed, follow other creators, and receive notifications.

---

#### US-20.1: Explore Page

**As a** listener, **I want** an Explore page showing trending songs, genre channels, staff picks, new releases, and charts, **so that** I can discover new music across the platform.

**Description:**
Build the Explore page at `/explore` with content sections from spec section 28: Trending (24h and 7d filters), Genre Channels, Staff Picks, New Releases, and Charts. Each section is a horizontally scrollable row of clip cards or a grid.

**Functional Requirements:**
- Trending section with 24h/7d time range toggle
- Genre Channels: horizontal row of genre tiles (Rock, Electronic, Hip Hop, Classical, etc.) linking to genre-filtered views
- Staff Picks: editorially curated highlights
- New Releases: chronological feed of recently published songs
- Charts: Top clips by plays, likes, or shares with ranking numbers
- Each song is a clickable clip card linking to the song detail page
- Sections are lazy-loaded for performance

**Acceptance Criteria:**
- [ ] Explore page renders all five content sections
- [ ] Trending section filters by 24h and 7d correctly
- [ ] Genre tiles navigate to genre-filtered views
- [ ] Charts display ranking numbers alongside clip cards
- [ ] Clicking any clip navigates to its song detail page

---

#### US-20.2: Search Page

**As a** listener, **I want** to search for songs by text, filter by genre, BPM, key, duration, and model, and sort results, **so that** I can find exactly the music I am looking for.

**Description:**
Build the Search page at `/search` with full-text search, attribute filters, and sort options from spec section 29.

**Functional Requirements:**
- Search input with real-time results (debounced)
- Search targets: song titles, lyrics, style tags, artist/username, playlists
- Filter panel: genre, BPM range, key, duration range, model version, creation date
- Sort options: relevance, newest, most popular
- Results rendered as clip cards in a grid or list view
- Empty state with helpful suggestions
- URL query parameters for shareable search links

**Acceptance Criteria:**
- [ ] Search returns results matching the query across titles, lyrics, tags, and artists
- [ ] Filters narrow results correctly (e.g., BPM 120-140 returns only clips in that range)
- [ ] Sort changes the ordering of results
- [ ] Search state is reflected in the URL for sharing
- [ ] Empty queries show an empty state with suggestions

---

#### US-20.3: Playlists

**As a** musician, **I want** to create, manage, and share playlists with custom cover art, **so that** I can curate collections of music and use them as inspiration for new generations.

**Description:**
Build playlist CRUD, song management, visibility controls, cover art, and the "Use as Inspiration" feature from spec section 30.

**Functional Requirements:**
- Create playlist: name input, optional description
- Rename and delete playlists (delete with confirmation)
- Add/remove songs from a playlist
- Drag-to-reorder songs within a playlist
- Public/private visibility toggle
- Cover art: auto-generated mosaic from first 4 song thumbnails, or custom upload
- Share link for public playlists
- "Use as Inspiration" button: feeds the playlist into a new generation as context (links to Add Inspiration modal)
- Playlist detail page showing all songs with playback controls

**Acceptance Criteria:**
- [ ] Playlists can be created, renamed, and deleted
- [ ] Songs can be added, removed, and reordered
- [ ] Public/private toggle changes playlist visibility
- [ ] Cover art shows auto-mosaic by default and supports custom upload
- [ ] "Use as Inspiration" opens the creation page with the playlist as context
- [ ] Share link works for public playlists

---

#### US-20.4: Short-Form Feed

**As a** listener, **I want** a vertical-scroll feed of short audio clips that auto-play as I scroll, **so that** I can discover music in a fast, engaging format.

**Description:**
Build the short-form feed at `/feed` from spec section 26. Each item is a full-screen or large-card audio player that auto-plays when scrolled into view, with title/artist/tag overlays and action buttons.

**Functional Requirements:**
- Vertical scroll layout with one item per viewport height (or large card)
- Auto-play audio when item scrolls into view; pause when it scrolls out
- Song title, artist name, and style tags as overlays on the card
- Action buttons: like, share, remix, use as inspiration
- Swipe or scroll to advance to the next item
- Feed algorithm: mix of trending clips, genre-matched recommendations, and followed-artist content
- Loading indicator for next items (infinite scroll)

**Acceptance Criteria:**
- [ ] Feed renders items in a vertical scroll layout
- [ ] Audio auto-plays when an item enters the viewport and pauses when it leaves
- [ ] Overlays display song title, artist, and style tags
- [ ] Like, share, remix, and use-as-inspiration buttons are functional
- [ ] Infinite scroll loads more items as the user reaches the bottom

---

#### US-20.5: Profile Page

**As a** listener, **I want** to view a musician's public profile showing their avatar, bio, published songs, playlists, and follower counts, **so that** I can explore their work and follow them.

**Description:**
Build the public profile page at `/@username` from spec section 32. Displays the creator's identity, published content, and social connections.

**Functional Requirements:**
- Avatar, display name, and bio prominently displayed
- Style tags rendered as pill badges
- Published songs grid (paginated)
- Playlists section
- Follower and following counts
- Follow/unfollow button (for authenticated users viewing others' profiles)
- Tab navigation between songs, playlists, and about sections
- Profile URL matches the user's handle (`/@username`)

**Acceptance Criteria:**
- [ ] Profile page loads at `/@username` with correct user data
- [ ] Published songs render in a grid with clip cards
- [ ] Follow button toggles follow state and updates follower count
- [ ] Style tags render as pill badges
- [ ] Playlists section shows the user's public playlists

---

#### US-20.6: Notifications Page

**As a** musician, **I want** a notifications page showing likes, remixes, followers, generation completions, mastering status, and distribution updates, **so that** I stay informed about activity related to my music.

**Description:**
Build the notifications page at `/notifications` from spec section 31. Each notification type has a distinct icon and links to the relevant content.

**Functional Requirements:**
- Notification types: liked/shared your song, remixed your song, new follower, generation complete, mastering job complete, distribution status update, system announcements
- Each notification shows: icon, message, timestamp, and link to relevant content
- Unread indicator (dot or badge) on unread notifications
- Mark as read (individual and mark all as read)
- Bell icon in sidebar shows unread count badge
- Real-time updates (WebSocket or polling) for new notifications
- Notification list is paginated or infinite-scroll

**Acceptance Criteria:**
- [ ] Notifications page lists all notification types with correct icons and messages
- [ ] Clicking a notification navigates to the relevant content (song, profile, release)
- [ ] Unread notifications show a visual indicator
- [ ] "Mark all as read" clears unread indicators
- [ ] Bell icon in sidebar shows unread count

---

#### US-20.7: Publish and Visibility Controls

**As a** musician, **I want** to set my clips as private, unlisted, or public from any clip location, **so that** I control who can see my work.

**Description:**
Implement the three-state visibility toggle (private, unlisted, public) from spec section 33. Publishing requires a title and at least one style tag.

**Functional Requirements:**
- Visibility toggle accessible from clip card, song detail page, and workspace
- Three states: Private (default), Unlisted (link-only access), Public (visible in feeds/search/explore)
- Publishing to Public requires: title is set and at least one style tag exists
- If requirements are not met, show an inline prompt to add the missing fields
- State change persists immediately via API
- Visual badge on clip cards indicating current visibility state

**Acceptance Criteria:**
- [ ] Visibility toggle switches between private, unlisted, and public
- [ ] Publishing without a title or style tag shows a prompt
- [ ] Visibility change persists after page reload
- [ ] Clip cards show a badge indicating current visibility state
- [ ] Unlisted clips are accessible via direct link but not in search/explore

---

**Stage 20 Completion Criteria:**
- Explore page displays trending, genres, staff picks, new releases, and charts
- Search returns results with filtering and sorting
- Playlists support full CRUD, reordering, cover art, and "Use as Inspiration"
- Short-form feed auto-plays audio on scroll
- Profile pages display public content and support follow/unfollow
- Notifications render all types with real-time updates
- Publish/visibility controls enforce title and style tag requirements
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 21: Mastering & Distribution UI

**Overview:** Build the release management pages where musicians master their songs through external services and distribute them to streaming platforms. This includes the mastering workflow (profile selection, service selection, multi-preview, A/B compare), distribution metadata forms, cover art, ISRC/UPC codes, SoundCloud OAuth, and a status dashboard. After this stage, the full prompt-to-distribution pipeline is operable through the browser.

---

#### US-21.1: Release Page Layout

**As a** musician, **I want** a dedicated release page with Mastering and Distribute tabs, **so that** I have a single destination for preparing and shipping my music.

**Description:**
Build the release page at `/release` with two primary tabs: Mastering and Distribute. The page accepts a song selection (from workspace, studio mixdown, or direct navigation) and guides the musician through mastering and distribution in sequence.

**Functional Requirements:**
- Route: `/release` with Mastering and Distribute tab navigation
- Song selector: choose a song from workspace or arrive with a pre-selected song (e.g., from "Send to Mastering" in Studio)
- Selected song summary: thumbnail, title, duration, current mastering/distribution status
- Tab state persisted in URL (e.g., `/release?tab=mastering`)
- Mastering tab is the default landing

**Acceptance Criteria:**
- [ ] Release page loads at `/release` with Mastering and Distribute tabs
- [ ] Song selector allows choosing from workspace clips
- [ ] Pre-selected song from Studio or clip context menu is loaded automatically
- [ ] Selected song summary displays correctly
- [ ] Tab navigation updates the URL and persists on refresh

---

#### US-21.2: Mastering Workflow

**As a** musician, **I want** to choose a mastering profile and service, preview up to 5 masters, and A/B compare with the original, **so that** I can get a professional-quality master tuned to my target platform.

**Description:**
Build the mastering tab workflow from spec section 41.3: profile selection, service selection, preview generation, audition, A/B comparison, and approval.

**Functional Requirements:**
- Mastering profile selector: Streaming (-14 LUFS), SoundCloud (-12 LUFS), Club/DJ, Vinyl, Custom (user-specified LUFS target)
- Service selector: Dolby.io (default), LANDR, Bakuage
- "Start Mastering" button submits the job
- Preview section: up to 5 mastered versions with playback controls
- A/B compare toggle: switch between original mix and mastered version during playback
- Approve button: selects the preferred master, saves to workspace with "Mastered" badge
- Mastering metrics display (when available): loudness (LUFS), EQ bands, stereo image
- Error state with retry option if mastering fails

**Acceptance Criteria:**
- [ ] All five mastering profiles are selectable
- [ ] All three mastering services are selectable
- [ ] Mastering job submits and shows progress
- [ ] Previews are playable when ready
- [ ] A/B toggle switches between original and mastered audio during playback
- [ ] Approving a master saves it to the workspace with the correct badge

---

#### US-21.3: Mastering Status Tracking

**As a** musician, **I want** to see the real-time status of my mastering jobs, **so that** I know when my masters are ready for review.

**Description:**
Display mastering job status as it progresses through the pipeline: Queued, Processing, Preview Ready, Approved, or Failed. Status updates in real time without requiring page refresh.

**Functional Requirements:**
- Status indicators: Queued, Processing, Preview Ready, Approved, Failed
- Real-time status updates (polling or WebSocket)
- Progress visualization (spinner, progress bar, or step indicator)
- Failed state shows error message and retry button
- Status visible on the mastering tab and in the notifications page
- History of past mastering jobs with their status and approved results

**Acceptance Criteria:**
- [ ] Status updates display in real time as the job progresses
- [ ] Each status state is visually distinct
- [ ] Failed jobs show an error message with a retry option
- [ ] Approved masters are accessible from the mastering history
- [ ] Mastering completion triggers a notification

---

#### US-21.4: Distribution Metadata Form

**As a** musician, **I want** a pre-populated metadata form for my release, **so that** I can review and edit song details before distributing.

**Description:**
Build the distribution tab metadata form from spec section 42.3-42.4. Fields are pre-populated from the song's existing metadata. The form includes cover art selection/generation and ISRC/UPC codes.

**Functional Requirements:**
- Pre-populated fields: title, artist, album name, genre, description, BPM, key, language, explicit content flag
- Editable fields: all pre-populated fields plus release date, copyright notice, credits (producer, songwriter, performer)
- Cover art section: select existing art, upload new art (3000x3000 minimum, JPG/PNG), or generate via AI (links to cover art generation)
- ISRC field: enter existing code or generate a new one
- UPC/EAN field: enter existing code or generate a new one
- Lyrics field: pre-populated, editable (synced or unsynced)
- Form validation: required fields highlighted, resolution check on cover art
- Save as draft functionality

**Acceptance Criteria:**
- [ ] Metadata form pre-populates from the selected song's data
- [ ] All fields are editable
- [ ] Cover art upload enforces 3000x3000 minimum resolution
- [ ] ISRC and UPC codes can be entered or auto-generated
- [ ] Form validation highlights missing required fields
- [ ] Draft can be saved and resumed later

---

#### US-21.5: Distribution Target Selection and SoundCloud OAuth

**As a** musician, **I want** to select distribution targets and connect my SoundCloud account, **so that** my music reaches listeners on their preferred platforms.

**Description:**
Build the distribution target selection UI and SoundCloud OAuth connection flow. SoundCloud is fully automated; LANDR and DistroKid are guided workflows with package preparation.

**Functional Requirements:**
- Target selection: SoundCloud (auto), LANDR (guided), DistroKid (guided)
- SoundCloud OAuth connect button: initiates OAuth 2.1 flow, stores token
- Connected SoundCloud account displays username and avatar
- Disconnect option for SoundCloud
- LANDR/DistroKid guided flow: prepares distribution package, provides instructions, opens external service in new tab
- Target-specific requirements displayed (e.g., SoundCloud metadata fields, LANDR format requirements)

**Acceptance Criteria:**
- [ ] SoundCloud OAuth connect flow completes and stores credentials
- [ ] Connected SoundCloud account shows username and avatar
- [ ] SoundCloud can be disconnected
- [ ] LANDR guided flow prepares package and opens LANDR in a new tab
- [ ] Target-specific requirements are displayed for each distribution channel

---

#### US-21.6: Distribution Status Dashboard and Review Screen

**As a** musician, **I want** to see the status of my distributions and review all assets before submission, **so that** I can track my releases and catch issues before they go live.

**Description:**
Build the distribution status dashboard from spec section 42.5 and the review/summary screen from spec section 42.4 step 7. The dashboard tracks releases through their lifecycle; the review screen provides a final check before submission.

**Functional Requirements:**
- Review/summary screen: displays all metadata, cover art, audio file details, selected targets, and ISRC/UPC before submission
- "Submit" button on review screen: triggers SoundCloud upload (auto) or opens guided flow
- Distribution status dashboard: shows all releases with status badges
- Status states: Draft, Ready, Submitted, In Review, Live, Rejected
- Rejected status shows the reason from the platform
- Status updates via real-time polling or notifications
- Direct links to live releases on external platforms

**Acceptance Criteria:**
- [ ] Review screen displays complete release package for final verification
- [ ] Submission triggers the correct workflow for each target
- [ ] Status dashboard shows all releases with correct status badges
- [ ] Status updates reflect changes from external platforms
- [ ] Rejected releases display the rejection reason
- [ ] Live releases link to their external platform pages

---

**Stage 21 Completion Criteria:**
- Release page provides mastering and distribution workflows in a single destination
- Mastering supports profile/service selection, multi-preview, A/B compare, and approval
- Mastering status tracks jobs in real time through all pipeline stages
- Distribution metadata form pre-populates and validates all required fields
- SoundCloud OAuth connect flow works end-to-end
- Distribution status dashboard tracks releases from draft to live
- Review screen provides a final verification before submission
- All features covered by tests (unit + E2E with Playwright)

---

