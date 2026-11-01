# #592 Web coverage is measurable, down to changed lines

*2026-11-01T02:26:52Z by Showboat 0.6.1*
<!-- showboat-id: 4749d41c-d274-45ff-b6bb-9e381960b45c -->

Before #592, `npx vitest run --coverage` failed with `MISSING DEPENDENCY: Cannot find dependency '@vitest/coverage-v8'`. Now it writes `coverage/lcov.info` with repo-root paths, and `diff-cover` reads it the way the Python gate reads `coverage.xml`.

```bash
cd web && npx vitest run --coverage 2>&1 | grep -E '^ *(Tests|Statements|Lines) ' | sed 's/ [0-9]*ms$//'; grep -m1 '^SF:web/' coverage/lcov.info
```

```output
      Tests  1921 passed (1921)
Statements   : 83.92% ( 7174/8548 )
Lines        : 86.95% ( 6570/7556 )
SF:web/app/favicon.ico
```

Changed-line coverage, measured against a main from four merges back. Those merges changed web code like `useClips`, `RelatedSongs`, `ClipCard` and the discovery surfaces:

```bash
uvx diff-cover web/coverage/lcov.info --compare-branch=origin/main~4 2>&1 | grep -E '\.tsx?|Total|Missing:|Coverage:' | tail -8
```

```output
web/lib/feed.ts (100%)
web/lib/mock-clips.ts (100%)
web/lib/notifications.ts (100%)
web/lib/playlists.ts (100%)
web/lib/search.ts (100%)
Total:   186 lines
Missing: 4 lines
Coverage: 97%
```
