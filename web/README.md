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
  store for transport, queue/history, volume, repeat/shuffle, likes; durable
  preferences persist to `localStorage`.
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
  `GET /api/v1/clips/{id}`; forwards the Bearer token, keeps the backend URL
  server-side.
- `app/api/clips/[id]/similar/route.ts` — same-origin BFF proxy for
  `GET /api/v1/clips/{id}/similar`; whitelists and bounds `scope`/`limit`
  before forwarding.
- `lib/waveform.ts` — `barHeights`, the seeded waveform bar generator (shared
  with the player `MiniWaveform`).
- `lib/clip-labels.ts` — display-label maps for clip model/generation_mode.
- `lib/proxy-fetch.ts` — `fetchWithTimeout` used by BFF routes.

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
