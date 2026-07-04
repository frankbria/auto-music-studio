"use client"

import { type PointerEvent as ReactPointerEvent, useCallback, useMemo, useRef } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { WAVEFORM_BARS as BARS, barHeights } from "@/lib/waveform"
import { formatMs, parseTimeString } from "@/lib/editing-validation"

// Range selector for the crop / replace-section / sample modals (US-17.3).
// Instead of a heavy audio-decoding dependency, it reuses the app's decorative
// waveform (`barHeights`, seeded from the clip id — the same bars the song page
// shows) and overlays a draggable [start, end] region. The numeric time inputs
// stay in sync with the handles and are the accessible, testable path; dragging
// is the visual convenience. Emits `start`/`end` as backend time strings.

function clampMs(ms: number, durationMs: number): number {
  return Math.max(0, Math.min(ms, durationMs))
}

function snap(ms: number, bpm: number | null | undefined, enabled: boolean): number {
  if (!enabled || !bpm || bpm <= 0) return ms
  const beatMs = 60000 / bpm
  return Math.round(ms / beatMs) * beatMs
}

export function RangeSelector({
  clipId,
  durationMs,
  start,
  end,
  onChange,
  snapToBeat = false,
  bpm = null,
}: {
  clipId: string
  durationMs: number
  start: string
  end: string
  onChange: (next: { start: string; end: string }) => void
  snapToBeat?: boolean
  bpm?: number | null
}) {
  const heights = useMemo(() => barHeights(clipId), [clipId])
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef<"start" | "end" | null>(null)

  const startMs = clampMs(parseTimeString(start) ?? 0, durationMs)
  const endMs = clampMs(parseTimeString(end) ?? durationMs, durationMs)
  const startPct = durationMs > 0 ? (startMs / durationMs) * 100 : 0
  const endPct = durationMs > 0 ? (endMs / durationMs) * 100 : 100

  const emit = useCallback(
    (handle: "start" | "end", ms: number) => {
      const snapped = clampMs(snap(ms, bpm, snapToBeat), durationMs)
      if (handle === "start") {
        onChange({ start: formatMs(Math.min(snapped, endMs)), end })
      } else {
        onChange({ start, end: formatMs(Math.max(snapped, startMs)) })
      }
    },
    [bpm, snapToBeat, durationMs, onChange, start, end, startMs, endMs]
  )

  // Pointer capture keeps events flowing to the grabbed handle even when the
  // cursor leaves it, so the drag stays live across the whole track without
  // manual window listeners (which the refs lint rightly flags).
  const onHandleMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const handle = dragging.current
    const track = trackRef.current
    if (!handle || !track) return
    const rect = track.getBoundingClientRect()
    if (rect.width <= 0) return
    const ratio = (e.clientX - rect.left) / rect.width
    emit(handle, Math.max(0, Math.min(1, ratio)) * durationMs)
  }

  const onHandleUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    dragging.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        ref={trackRef}
        className="relative flex h-16 w-full items-center gap-[2px] overflow-hidden rounded-md bg-muted/40 px-1"
        aria-label="Selection range"
      >
        {heights.map((h, i) => {
          const barPct = ((i + 0.5) / BARS) * 100
          const selected = barPct >= startPct && barPct <= endPct
          return (
            <div
              key={i}
              className={selected ? "flex-1 bg-primary" : "flex-1 bg-muted-foreground/40"}
              style={{ height: `${Math.max(6, h * 100)}%` }}
            />
          )
        })}
        <div
          className="pointer-events-none absolute inset-y-0 border-x-2 border-primary/70 bg-primary/10"
          style={{ left: `${startPct}%`, right: `${100 - endPct}%` }}
        />
        <button
          type="button"
          aria-label="Selection start"
          onPointerDown={(e) => {
            dragging.current = "start"
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
          className="absolute top-0 h-full w-3 -translate-x-1/2 cursor-ew-resize rounded bg-primary"
          style={{ left: `${startPct}%` }}
        />
        <button
          type="button"
          aria-label="Selection end"
          onPointerDown={(e) => {
            dragging.current = "end"
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
          className="absolute top-0 h-full w-3 -translate-x-1/2 cursor-ew-resize rounded bg-primary"
          style={{ left: `${endPct}%` }}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${clipId}-range-start`}>Start</Label>
          <Input
            id={`${clipId}-range-start`}
            value={start}
            onChange={(e) => onChange({ start: e.target.value, end })}
            placeholder="0s"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${clipId}-range-end`}>End</Label>
          <Input
            id={`${clipId}-range-end`}
            value={end}
            onChange={(e) => onChange({ start, end: e.target.value })}
            placeholder={formatMs(durationMs)}
          />
        </div>
      </div>
    </div>
  )
}
