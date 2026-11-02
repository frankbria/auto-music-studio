# Accessibility (US-28.3, #340)

Target: WCAG 2.1 AA. How it is checked, and where the app stood on 2026-11-02.

## Automated audit

`scripts/a11y-audit.mjs` runs axe-core (WCAG 2.0/2.1 A and AA rules) on every page of a deployment in Chrome:
- signed out: home, Explore, Search (empty and with results), Feed, Login, Support, a song page and a 404;
- signed in: Create, Studio, Me, Settings (profile, billing, usage), Playlists, Notifications, Release, and a song's
  page, editor and video page.

Usage is in the script's header.

On staging at `1958ff1`, axe found **no critical violations** on any page. The serious ones it found were fixed in
the PR that added this file:

| Rule | Where | Fix |
| --- | --- | --- |
| `color-contrast` | Every tab bar (Create, Studio, Release): inactive tab text 4.34:1 on the tab background | Inactive tabs use `foreground/70` |
| `color-contrast` | Search's "Coming soon" filter placeholders, dimmed to 1.96:1 with `opacity-50` | Muted text without the opacity |
| `color-contrast` | Green status text (`emerald-500`, 2.47:1) on Release, mastering and SoundCloud | `emerald-700` (`emerald-400` in dark mode) |
| `label-content-name-mismatch` | Model selector named "Select model" while showing the model | "Select model: <model>" |
| `label-content-name-mismatch` | Workspace clip card: thumbnail "Play" showing a duration; title button "Edit title" showing the title | "Play <title>" with the duration hidden from assistive tech; "Edit title: <title>" |
| `label-content-name-mismatch` | Pagination: "Prev" named "Previous page" | Visible text "Previous" |

## Keyboard and screen readers

- **Skip to content** is the first Tab stop on every page and moves focus to `main#main-content`.
- **Player:** every control is a native button or range input, so it is reachable by Tab and operated with
  Space/Enter and the arrow keys. The seek bar reads as "1:05 of 3:20" and volume as a percentage
  (`aria-valuetext`), not raw numbers.
- **Announcements:** Next's route announcer reads page changes; generation progress, loading rows and the
  connection banner are `role="status"`; errors are `role="alert"`, and form errors are tied to their field with
  `aria-describedby` (#339).
- **Modals** are Radix dialogs: focus is trapped inside while open and returns to the trigger on close.
