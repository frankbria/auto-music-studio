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
- `BottomPlaybar` — fixed bottom bar (player controls arrive in US-15.6);
  rendered in `app/layout.tsx` as a sibling of `AppShell` so it stays
  viewport-anchored.

Shared dimensions and the z-index scale live in `lib/constants/layout.ts`.

Run the layout smoke tests with `npm run test`.

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
