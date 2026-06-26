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
