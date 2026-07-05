// Pure viewport math for the waveform editor (US-18.1). Kept free of React and
// canvas so the zoom / scroll / tick-interval logic is unit-testable in
// isolation. All audio positions are in seconds; `x` is a pixel offset from the
// left edge of the visible viewport (not the whole clip — the canvas is
// virtual-scrolled, so it only ever draws `width` pixels).

/** Zoom-in ceiling, in canvas pixels per second (~sample-level detail). */
export const MAX_PX_PER_SEC = 4000

/** The visible window: how zoomed in we are, and where the left edge sits. */
export type Viewport = {
  /** Horizontal zoom: canvas pixels per second of audio. */
  pxPerSec: number
  /** Left edge of the visible window, in seconds from the clip start. */
  scrollSec: number
}

/**
 * px/sec at which the whole clip exactly fills `width`. This is the min-zoom
 * floor: you can never zoom out further than "the entire clip on screen".
 */
export function fitPxPerSec(duration: number, width: number): number {
  if (duration <= 0 || width <= 0) return 1
  return width / duration
}

/** Clamp a desired zoom to [fit, MAX]. */
export function clampPxPerSec(
  px: number,
  duration: number,
  width: number
): number {
  const min = fitPxPerSec(duration, width)
  return Math.min(MAX_PX_PER_SEC, Math.max(min, px))
}

/** Largest scrollSec that keeps the right edge of the window within the clip. */
export function maxScrollSec(
  duration: number,
  pxPerSec: number,
  width: number
): number {
  const visibleSec = pxPerSec > 0 ? width / pxPerSec : duration
  return Math.max(0, duration - visibleSec)
}

/** Clamp a desired scroll position to [0, maxScrollSec]. */
export function clampScrollSec(
  scrollSec: number,
  duration: number,
  pxPerSec: number,
  width: number
): number {
  return Math.min(
    maxScrollSec(duration, pxPerSec, width),
    Math.max(0, scrollSec)
  )
}

/** Screen x (px) for an audio time, under the given viewport. */
export function secToX(sec: number, vp: Viewport): number {
  return (sec - vp.scrollSec) * vp.pxPerSec
}

/** Audio time (sec) for a screen x (px), under the given viewport. */
export function xToSec(x: number, vp: Viewport): number {
  return vp.scrollSec + x / vp.pxPerSec
}

/**
 * Zoom to `nextPx` while pinning the audio currently under screen-x `anchorX`
 * in place — so wheel-zoom homes on the cursor and +/- buttons hold the view
 * centre (AC: "maintain center point when zoom level changes"). Returns a fully
 * clamped viewport.
 */
export function zoomAtX(
  vp: Viewport,
  nextPx: number,
  anchorX: number,
  duration: number,
  width: number
): Viewport {
  const pxPerSec = clampPxPerSec(nextPx, duration, width)
  const anchorSec = xToSec(anchorX, vp) // audio pinned under the anchor
  const scrollSec = clampScrollSec(
    anchorSec - anchorX / pxPerSec,
    duration,
    pxPerSec,
    width
  )
  return { pxPerSec, scrollSec }
}

// Ruler tick spacing. A "nice" ladder of intervals (seconds) so labels land on
// human-friendly boundaries; we pick the smallest step that keeps labels at
// least ~TARGET_TICK_PX apart, so the ruler stays readable at every zoom.
const TICK_LADDER = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
const TARGET_TICK_PX = 80

/** Seconds between major ruler ticks at the given zoom. */
export function chooseTickInterval(pxPerSec: number): number {
  if (pxPerSec <= 0) return TICK_LADDER[TICK_LADDER.length - 1]
  const targetSec = TARGET_TICK_PX / pxPerSec
  for (const step of TICK_LADDER) if (step >= targetSec) return step
  return TICK_LADDER[TICK_LADDER.length - 1]
}

export type Tick = { sec: number; x: number }

/** Major ticks visible in the viewport, each with its screen-x position. */
export function visibleTicks(
  vp: Viewport,
  width: number,
  duration: number
): Tick[] {
  const interval = chooseTickInterval(vp.pxPerSec)
  const ticks: Tick[] = []
  // scrollSec is always ≥ 0 (clamped), so the first tick index is ≥ 0; the
  // Math.max also normalizes a -0 from Math.ceil back to +0.
  const first = Math.max(0, Math.ceil(vp.scrollSec / interval - 1e-9)) * interval
  for (let sec = first; sec <= duration + 1e-6; sec += interval) {
    const x = secToX(sec, vp)
    if (x > width) break
    if (x >= 0) ticks.push({ sec, x })
  }
  return ticks
}
