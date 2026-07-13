// Pure timeline math for the Studio multi-track editor (US-19.1). Kept free of
// React/canvas so zoom, ruler ticks, and playback scheduling stay unit-testable
// in isolation, mirroring lib/waveform-viewport.ts. Unlike the single-clip
// waveform viewport, the studio timeline has no natural "fit" duration — zoom is
// expressed as a multiplier of a fixed base px/sec instead of a fit-to-width
// floor.

import {
  secToX,
  xToSec,
  visibleTicks,
  type Viewport,
} from "./waveform-viewport"

export type { Viewport }
export { secToX, xToSec }

/** px/sec at zoom level 1. */
export const BASE_PX_PER_SEC = 100

/**
 * Width, in px, of each TrackLane's left control strip (name/color). The
 * ruler and playhead sit in the same outer container as the lanes but don't
 * have a strip of their own, so anything positioned by seconds × pxPerSec
 * needs this added to land under the lanes' actual timeline region rather
 * than under their strips. A single exported constant so the ruler's spacer,
 * the lane's strip, and the playhead's offset can't drift apart.
 */
export const TRACK_STRIP_PX = 160

export const MIN_ZOOM = 0.25
export const MAX_ZOOM = 4

/** Clamp a zoom multiplier to [MIN_ZOOM, MAX_ZOOM]. */
export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

/** px/sec for a given zoom multiplier, clamped to the supported range. */
export function zoomToPxPerSec(zoom: number): number {
  return BASE_PX_PER_SEC * clampZoom(zoom)
}

export type DisplayMode = "bars-beats" | "mm-ss"

export const DEFAULT_BPM = 120
const BEATS_PER_BAR = 4

/** Grid resolutions for snap-to-grid, as fractions of a beat/bar (US-19.3). */
export type SnapResolution = "1bar" | "1beat" | "1/2beat" | "1/4beat"

const SNAP_BEATS: Record<SnapResolution, number> = {
  "1bar": BEATS_PER_BAR,
  "1beat": 1,
  "1/2beat": 0.5,
  "1/4beat": 0.25,
}

/** Seconds between grid lines for a snap resolution at the given tempo. */
export function snapStepSec(resolution: SnapResolution, bpm: number): number {
  return (60 / bpm) * SNAP_BEATS[resolution]
}

/** Quantize a time to the nearest grid line (never negative). */
export function snapSec(
  sec: number,
  resolution: SnapResolution,
  bpm: number
): number {
  const step = snapStepSec(resolution, bpm)
  return Math.max(0, Math.round(sec / step) * step)
}

/** A ruler tick: audio time, screen-x, and its display label. */
export type TimelineTick = { sec: number; x: number; label: string }

function formatMmSs(sec: number): string {
  const total = Math.max(0, Math.round(sec))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

function formatBarsBeats(sec: number, bpm: number): string {
  const beatSec = 60 / bpm
  const totalBeats = Math.round(sec / beatSec)
  const bar = Math.floor(totalBeats / BEATS_PER_BAR) + 1
  const beat = (totalBeats % BEATS_PER_BAR) + 1
  return `${bar}.${beat}`
}

// Ladder of bar counts between major ticks, so labels stay readable at every
// zoom without ever landing off a bar boundary (mirrors the second-based
// TICK_LADDER in waveform-viewport.ts).
const BAR_LADDER = [1, 2, 4, 8, 16, 32, 64, 128, 256]
const TARGET_TICK_PX = 80

/** Bars between major ticks at the given zoom, for a bar of `barSec` seconds. */
function chooseBarInterval(pxPerSec: number, barSec: number): number {
  if (pxPerSec <= 0) return BAR_LADDER[BAR_LADDER.length - 1]
  const targetBars = TARGET_TICK_PX / pxPerSec / barSec
  for (const bars of BAR_LADDER) if (bars >= targetBars) return bars
  return BAR_LADDER[BAR_LADDER.length - 1]
}

/** Ruler ticks visible in the viewport, labeled for the given display mode. */
export function timelineTicks(
  vp: Viewport,
  width: number,
  durationSec: number,
  mode: DisplayMode,
  bpm: number = DEFAULT_BPM
): TimelineTick[] {
  if (mode === "mm-ss") {
    return visibleTicks(vp, width, durationSec).map((t) => ({
      ...t,
      label: formatMmSs(t.sec),
    }))
  }

  const barSec = (60 / bpm) * BEATS_PER_BAR
  const interval = chooseBarInterval(vp.pxPerSec, barSec) * barSec
  const ticks: TimelineTick[] = []
  const first =
    Math.max(0, Math.ceil(vp.scrollSec / interval - 1e-9)) * interval
  for (let sec = first; sec <= durationSec + 1e-6; sec += interval) {
    const x = secToX(sec, vp)
    if (x > width) break
    if (x >= 0) ticks.push({ sec, x, label: formatBarsBeats(sec, bpm) })
  }
  return ticks
}

/** A clip placed on a track at a given start time (see contexts/studio-context.tsx). */
export type Placement = {
  id: string
  clipId: string
  startSec: number
  title: string | null
  durationSec: number | null
  /** The source clip's own BPM (US-19.2) — kept on the placement so a
   * loop-track clip's playback rate can be re-derived whenever the project
   * tempo changes, instead of freezing a multiplier at drop time. */
  clipBpm?: number | null
}

/** Timeline never renders shorter than this, even with no clips placed. */
export const MIN_TIMELINE_SEC = 60
/** Trailing room past the furthest clip, so there's always room to drop more. */
const TIMELINE_PADDING_SEC = 20

/**
 * Total timeline length: the floor, or far enough to fit every placement (plus
 * padding to drop new clips past the end), whichever is longer.
 */
export function timelineDurationSec(placements: Placement[]): number {
  const furthestEnd = placements.reduce(
    (max, p) => Math.max(max, p.startSec + (p.durationSec ?? 0)),
    0
  )
  return Math.max(MIN_TIMELINE_SEC, furthestEnd + TIMELINE_PADDING_SEC)
}

/** One clip scheduled to play through the studio's AudioContext. */
export type ScheduledClip = {
  clipId: string
  /** AudioContext-relative time to start this source (>= audioContextNow). */
  when: number
  /** Offset into the clip's buffer to start playback from, in seconds. */
  offset: number
  /** AudioBufferSourceNode.playbackRate for this clip (US-19.2 loop tempo). */
  playbackRate: number
}

/**
 * Compute which placements should sound, and when/where, given playback
 * starting at `playheadSec` and the AudioContext's current time
 * (`audioContextNow`, i.e. `ctx.currentTime`). Placements that have already
 * finished by the playhead are skipped; ones already in progress start now
 * with a nonzero buffer offset; future ones are scheduled at their absolute
 * start time. Placements with no known duration are treated as playing
 * through to the end (never pre-emptively excluded).
 *
 * `rateFor` supplies each placement's playback rate (loop-track tempo
 * matching, US-19.2): a rate ≠ 1 compresses/stretches the clip on the
 * timeline (durationSec/rate) and scales the buffer offset for in-progress
 * clips, since timeline seconds pass `rate`× faster inside the buffer.
 */
export function computePlaybackSchedule(
  placements: Placement[],
  playheadSec: number,
  audioContextNow: number,
  rateFor: (p: Placement) => number = () => 1
): ScheduledClip[] {
  const schedule: ScheduledClip[] = []
  for (const p of placements) {
    const rate = rateFor(p)
    const duration = p.durationSec == null ? Infinity : p.durationSec / rate
    const endSec = p.startSec + duration
    if (endSec <= playheadSec) continue
    const offset = Math.max(0, playheadSec - p.startSec) * rate
    const when = audioContextNow + Math.max(0, p.startSec - playheadSec)
    schedule.push({ clipId: p.clipId, when, offset, playbackRate: rate })
  }
  return schedule.sort((a, b) => a.when - b.when)
}
