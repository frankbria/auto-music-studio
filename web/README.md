# Auto Music Studio — Web UI (Layer 3)

Next.js 16 app built on the Shadcn Nova template (gray palette, Hugeicons, Nunito Sans). See the root [README](../README.md) for the full project.

## Application shell (US-15.2)

The four-zone shell lives in `components/layout/` and wraps every route via
`app/layout.tsx`:

- `AppShell` — flex container: `Sidebar` + `<main>` (route content) + optional
  `RightPanel`. Reserves bottom space for the playbar.
- `Sidebar` — 64px collapsed icon bar (nav icons arrive in US-15.3).
- `RightPanel` — 320px contextual panel, hidden below `lg` (1024px). Render
  content into it by passing `rightPanel` to `AppShell`.
- `BottomPlaybar` — fixed bottom bar; rendered in `app/layout.tsx` as a sibling
  of `AppShell` so it stays viewport-anchored. Wraps the player (US-15.6).

Shared dimensions and the z-index scale live in `lib/constants/layout.ts`.

Run the layout smoke tests with `npm run test`.

## Global player (US-15.6)

A persistent bottom player that keeps playing across client-side navigation.

- `contexts/player-context.tsx` — `PlayerProvider` + `usePlayer`: a reducer
  store for transport, queue/history, volume, repeat/shuffle, and likes/dislikes
  (mutually exclusive per clip); durable preferences persist to `localStorage`.
- `hooks/use-audio-engine.ts` — owns the single `<audio>` element (mounted once
  at the shell level) and syncs it to the store both ways.
- `hooks/use-player-shortcuts.ts` — space / arrows / `m`, ignored while typing.
- `components/player/` — `Playbar` and its controls (transport, scrubber,
  volume, mini-waveform, song info, queue panel, mode toggles, like).
- `lib/clips.ts` builds the backend media URLs; `lib/demo-tracks.ts` +
  `public/demo/sample.wav` seed a demo queue until a clip-browsing UI exists.

## Song Detail Page (US-17.1)

The `/song/[id]` route renders a full-page view of a single clip.

- `app/song/[id]/page.tsx` — thin route shim: extracts `id` from params and
  delegates to `SongDetail`.
- `components/song/SongDetail.tsx` — top-level component; owns auth guard, data
  fetching, and the three-column layout (header + player + metadata / lyrics /
  related songs).
- `components/song/SongHeader.tsx` — title, artist placeholder, style/version/
  mode badges, and the inline like/dislike/share/publish row.
- `components/song/SongPlayer.tsx` — play/pause + `SongWaveform` + time readout,
  driven through the global `usePlayer` store.
- `components/song/SongWaveform.tsx` — canvas waveform (deterministic bars
  seeded by clip id via `lib/waveform.ts`); click-to-seek when the clip is the
  current player track.
- `components/song/SongMetadata.tsx` — model/BPM/key/duration/created/visibility
  grid (null fields omitted).
- `components/song/SongLyrics.tsx` — scrollable lyrics with structure tags
  (`[Verse]`/`[Chorus]`) formatted as section labels.
- `components/song/RelatedSongs.tsx` — "Related songs" panel fed by
  `useSimilarClips`.
- `hooks/use-clip.ts` — fetches a single clip from the same-origin BFF; tags
  results with the requested id to prevent stale renders across `/song/:id`
  navigations.
- `hooks/use-similar-clips.ts` — fetches similar clips from the BFF.
- `app/api/clips/[id]/route.ts` — same-origin BFF proxy for
  `GET`/`DELETE /api/v1/clips/{id}`; forwards the Bearer token, keeps the
  backend URL server-side.
- `app/api/clips/[id]/similar/route.ts` — same-origin BFF proxy for
  `GET /api/v1/clips/{id}/similar`; whitelists and bounds `scope`/`limit`
  before forwarding.
- `lib/waveform.ts` — `barHeights`, the seeded waveform bar generator (shared
  with the player `MiniWaveform`).
- `lib/clip-labels.ts` — display-label maps for clip model/generation_mode.
- `lib/proxy-fetch.ts` — `fetchWithTimeout` used by BFF routes.

## Full Action Menu (US-17.2)

The song detail page's primary action button opens the full action menu — every
edit, remix, audio, export, and manage operation on a song in one place.

- `lib/song-actions.ts` — the shared action registry: grouped definitions
  (label, icon, workflow, Pro-gating) that both `SongActionsMenu` and
  `ClipCard`'s menus draw from, so the two surfaces can't drift apart.
- `hooks/use-song-actions.ts` — dispatches a selected action to its workflow:
  navigation (studio, or the waveform editor via `open-editor` — US-18.1), a
  workflow modal, a file download, or an inline operation (publish toggle —
  optimistic with a
  title/style-tag guard and rollback, persisted via `PATCH /clips/{id}`
  (US-17.6) — and delete with confirmation).
- `hooks/use-subscription-tier.ts` — lightweight subscription-tier lookup used
  to lock Pro-only menu items for free-tier users, without mounting the full
  model-selection context.
- `components/song/SongActionsMenu.tsx` — the grouped dropdown menu, purely
  presentational; renders the registry and emits the chosen action id.
- `components/song/SongActionModal.tsx` — placeholder container for
  modal-workflow actions; each item already opens a modal, with real workflow
  content landing story by story in US-17.3+.
- `components/song/DeleteSongDialog.tsx` — delete confirmation; keeps the
  dialog open with an error on failure so the user can retry or cancel.
- `app/api/clips/[id]/audio/route.ts` — same-origin BFF proxy for
  `GET /api/v1/clips/{id}/audio`; forwards the Bearer token and an optional
  `format` query (mp3/wav/flac) for the menu's Download items.
- `lib/clips.ts` — `downloadClipAudio` fetches the audio proxy with the
  in-memory token and hands the blob to the browser via a temporary
  object-URL anchor.

## Editing Workflow Modals (US-17.3)

Modal-based UIs for every editing/iterative operation reachable from the full
action menu, plus a one-click inline remaster.

- `lib/editing.ts` — typed client: one `submit*` function per operation
  (crop, speed, remaster, extend, cover, remix, repaint, sample, add-vocal,
  mashup), each posting a payload to its BFF route and classifying the
  response into an `EditSubmitResult` (accepted/unauthorized/invalid/
  insufficient-credits/error).
- `hooks/use-clip-edit.ts` — `useClipEdit`, a self-contained state machine
  (idle → submitting → polling → success/error) any modal can drop in; polls
  the job-status endpoint after a 202 and exposes the resulting clip ids.
- `components/song/SongActionModal.tsx` — dispatches the selected action id
  to its modal (`repaint` and `replace-section` both open Replace Section);
  actions whose workflows land in later stories still show the "not
  available yet" placeholder.
- `components/song/modals/` — one modal per operation (`CropModal`,
  `SpeedModal`, `ExtendModal`, `CoverModal`, `RemixModal`,
  `ReplaceSectionModal`, `SampleModal`, `AddVocalModal`, `MashupModal`), built
  on shared pieces: `EditModalShell` (phase-driven chrome: form → spinner →
  success-with-link → error-with-retry), `RangeSelector` (waveform range
  picker), `TimeDurationInput`, `StyleTextarea`, and `ClipMultiSelector`
  (mashup's 2+ clip picker).
- `components/song/RemasterStatus.tsx` — inline progress/success/error for
  the one-click Remaster action, which has no modal of its own.
- `lib/editing-validation.ts` / `lib/constants/editing.ts` — per-modal form
  validation and shared option lists (blend modes, sample roles).
- `lib/edit-proxy.ts` — `forwardEdit` / `clipEditRoute`, the shared same-origin
  proxy powering `app/api/clips/[id]/{crop,speed,remaster,extend,cover,remix,
  repaint,sample,add-vocal}/route.ts` and `app/api/mashup/route.ts`; forwards
  the Bearer token and passes backend status/body through unchanged.

## Waveform Editor (US-18.1)

The `/editor/[id]` route is the waveform editor — the foundation of Stage 18.
Reached from the song menu's Pro-only "Open in Editor" action (`open-editor`,
now a `navigation` workflow in `lib/song-actions.ts`).

- `app/editor/[id]/page.tsx` — thin route shim; delegates to `ClipEditor`.
- `components/editor/ClipEditor.tsx` — owns the auth guard, the **Pro-tier gate**
  (`useSubscriptionTier`, enforced before any audio is fetched — direct
  navigation can't bypass the menu lock), clip fetch, and audio-decode states.
- `components/editor/WaveformEditor.tsx` — owns the viewport (zoom + scroll),
  loads the clip into the global `usePlayer` store so the playhead + click-to-seek
  reuse the real audio engine, and composes the ruler / canvas / controls / scrollbar.
- `components/editor/WaveformCanvas.tsx` — virtual-scrolled canvas (viewport-sized,
  re-buckets only the visible window) with click-seek, drag-pan, Ctrl+wheel zoom,
  and pinch. Unlike `SongWaveform`, it draws **real** peaks.
- `components/editor/TimeRuler.tsx` / `ZoomControls.tsx` / `WaveformScrollbar.tsx`.
- `lib/audio-peaks.ts` — `decodeClipAudio` (fetches the authed `/api/clips/{id}/audio`
  proxy and decodes via Web Audio) + `columnPeaks` (per-pixel amplitude peaks;
  accurate at any zoom). This is the real waveform; `lib/waveform.ts`'s seeded
  bars still back the mini-player / song page.
- `lib/waveform-viewport.ts` — pure zoom/scroll/tick math (fit, anchor-preserving
  zoom, scroll clamp, adaptive `chooseTickInterval`).
- `hooks/use-clip-audio.ts` — id-tagged decode hook (mirrors `useClip`).

## Studio Timeline and Track Lanes (US-19.1)

The `/studio` route is the in-browser multi-track arrangement canvas — a
horizontal timeline of stacked track lanes with drag-and-drop clip placement.
Reached from the song menu's "Open in Studio" action (`open-studio` in
`lib/song-actions.ts`), which preloads the clip via `?song={id}`.

- `app/studio/page.tsx` — thin auth-gated route (mirrors `app/create/page.tsx`);
  `useSongPreload` adds the `?song=` clip to a fresh track at 0s once per clip
  id per session. Composes the header (transport, bars-beats/mm:ss toggle,
  zoom buttons + Ctrl/Cmd+wheel zoom), the scrollable timeline, and the
  workspace panel as a drag source (hidden below `lg`, like the app shell's
  `RightPanel`).
- `contexts/studio-context.tsx` — `StudioProvider` + `useStudio`: a reducer
  store for tracks/clip placements, playhead, play state, zoom, display mode,
  and a `seekEpoch` that the playback engine watches to reschedule audio after
  a user seek instead of a stale rAF tick stomping it.
- `hooks/use-studio-playback.ts` — `useStudioPlayback`, a dedicated
  `AudioContext` + master gain node that schedules every track's placements
  and drives the playhead from `ctx.currentTime` via `requestAnimationFrame`.
  Starting studio playback pauses the global player (the two never sound at
  once) rather than routing through it.
- `components/studio/TimeRuler.tsx` — bars+beats or mm:ss ticks over the
  timeline; click/drag to seek.
- `components/studio/TrackLane.tsx` / `AddTrackButton` — one lane per track
  with a name/color control strip (`lib/timeline.ts`'s `TRACK_STRIP_PX`) and a
  drop target for clips.
- `components/studio/ClipBlock.tsx` — a placed clip rendered as a block with
  title and waveform thumbnail; draggable to reposition within/between lanes.
- `components/studio/Playhead.tsx` / `TransportControls.tsx` — the timeline
  playhead line and play/pause/stop/return-to-start controls.
- `lib/timeline.ts` — pure timeline math (zoom↔px/sec, ruler ticks, playback
  scheduling), free of React/canvas, mirroring `lib/waveform-viewport.ts`.
- `lib/clip-audio-cache.ts` — decodes a clip's audio once, caching both the
  `AudioBuffer` (for playback) and a fixed-resolution peak downsample (for
  `ClipBlock`'s thumbnail).
- `lib/clip-drag.ts` — the shared `dataTransfer` JSON contract for dragging a
  clip onto the timeline: an "add" payload from `ClipCard` (workspace panel)
  or a "move" payload from `ClipBlock` repositioning an existing placement;
  centralizes the wire shape so drag sources and the lane's drop handler can't
  drift apart.

## Adding components

To add components to your app, run the following command:

```bash
npx shadcn@latest add button
```

This will place the ui components in the `components` directory.

## Using components

To use the components in your app, import them as follows:

```tsx
import { Button } from "@/components/ui/button"
```
