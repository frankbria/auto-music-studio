"use client"

// A vertical cursor over the Studio timeline (US-19.1), positioned purely from
// playheadSec × pxPerSec — a sibling overlay meant to span the full height of
// the ruler + track lanes it's layered on top of (parent supplies the
// positioning context and height; this only owns its own x).

export function Playhead({
  playheadSec,
  pxPerSec,
}: {
  playheadSec: number
  pxPerSec: number
}) {
  return (
    <div
      data-testid="playhead"
      aria-hidden="true"
      className="pointer-events-none absolute top-0 bottom-0 z-10 w-px bg-primary"
      style={{ left: playheadSec * pxPerSec }}
    />
  )
}
