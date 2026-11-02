# Performance (US-28.1, #338)

The targets, how each is measured, and where the platform stood on 2026-11-02. Re-run these before a release that
touches discovery, the player or the bundle.

## Targets and results

| Target | Result (2026-11-02) | How it was measured |
| --- | --- | --- |
| Time to Interactive under 3 s | 1.5–2.7 s on every page measured | Lighthouse 13, desktop, against staging |
| Lighthouse performance above 80 | 91–100 | Same runs |
| API reads under 200 ms at p95 | Under 20 ms on staging; under 50 ms for every discovery sort at scale | See below |
| Audio starts within 1 s, no full download first | Streaming with `Range`, `206` passed through the BFF | `app/api/clips/[id]/stream` |
| Page navigation without full reloads | No internal `<a href>`; every route link is `next/link` | Code sweep |

Lighthouse, per page (staging, build `d395e7a`):

| Page | Score | TTI | LCP | Total transfer |
| --- | --- | --- | --- | --- |
| /explore | 98 | 1.5 s | 0.9 s | 461 KiB |
| /search | 99 | 2.1 s | 2.1 s | 450 KiB |
| /feed | 99 | 2.3 s | 2.3 s | 454 KiB |
| /song/{id} | 97 | 2.4 s | 2.4 s | 477 KiB |
| /studio (signed in) | 97 | 2.7 s | 2.6 s | 489 KiB |
| /create (signed in) | 97 | 2.7 s | 2.7 s | 491 KiB |
| /me (signed in) | 100 | 1.9 s | 0.9 s | 486 KiB |
| /release (signed in) | 91 | 2.4 s | 2.4 s | 489 KiB |

```bash
CHROME_PATH=/usr/bin/google-chrome npx -y lighthouse https://dev.automusicstudio.com/explore \
  --only-categories=performance --chrome-flags="--headless=new --no-sandbox" --output=json --output-path=explore.json
```

Signed-in pages need a session: mint a refresh token for a staging user with `create_refresh_token` +
`store_refresh_token` and pass `--extra-headers='{"Cookie":"ams_refresh_token=<token>"}'`. Each page load rotates the
token, so mint one per page, and keep a run only if its network log includes `/api/credits/balance`. That call is
made only by a signed-in session; a refused token falls back to anonymous and still renders.

## API reads at scale

Staging's data is small, so discovery was also timed against a throwaway database of 20,000 public clips and 200,000
engagement rows in the last week (about 20 plays a minute), 30 calls per sort, 20 per page
(`uv run python scripts/perf_discovery.py`, against a local MongoDB):

| Sort | p50 | p95 |
| --- | --- | --- |
| newest | 14 ms | 15 ms |
| popular | 14 ms | 14 ms |
| staff_picks | 2 ms | 2 ms |
| relevance (`$text`) | 40 ms | 42 ms |
| trending_24h | 3 ms | 4 ms |
| trending_7d | 3 ms | 4 ms |

Trending was 430 ms at p50 (463 ms p95) for the 7-day window before its ranking was cached: the aggregation reads every
engagement row in the window. It now runs once per window per process every `TRENDING_TTL_SECONDS` (60 s), and pages
are cut from the cached ranking, so one request a minute pays that cost; requests arriving during a rebuild wait for
it rather than each running the aggregation.

## Caching

- `/_next/static/*` is content-hashed and served `public, max-age=31536000, immutable` by Next.
- Pages, and the files in `web/public`, are `private, no-cache` (`web/next.config.ts`); Next serves public files with
  `max-age=0` anyway, so they lose nothing. Next marks a prerendered page `s-maxage=31536000`, so a CDN
  would keep serving the previous deploy's HTML, whose chunk hashes no longer exist, until it was purged.
- Public clip audio is `public, max-age=300`, private audio `private, no-store`, both with `Accept-Ranges: bytes`.
- nginx compresses responses (gzip).

## Bundle

No heavy client libraries are installed: the waveform, studio timeline and players are the app's own components.
The heaviest routes (Studio, Create) add about 180 KiB of uncompressed route code over Explore and still score 97, so
nothing is split out with `next/dynamic`. Revisit if a route's Lighthouse score drops under 90 or a large
dependency arrives.
