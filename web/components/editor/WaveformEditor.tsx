"use client"

import { useEffect, useLayoutEffect, useRef, useState } from "react"

import { SelectionInfo } from "@/components/editor/SelectionInfo"
import { SelectionOverlay } from "@/components/editor/SelectionOverlay"
import { TimeRuler } from "@/components/editor/TimeRuler"
import { WaveformCanvas } from "@/components/editor/WaveformCanvas"
import { WaveformScrollbar } from "@/components/editor/WaveformScrollbar"
import { ZoomControls } from "@/components/editor/ZoomControls"
import { usePlayer } from "@/contexts/player-context"
import { useEditorShortcuts } from "@/hooks/use-editor-shortcuts"
import type { ClipAudio } from "@/lib/audio-peaks"
import { trackFromClip } from "@/lib/clips"
import {
  insertRegion,
  normalizeRegion,
  removeRegion,
  sliceRegion,
  type EditOperation,
  type Region,
} from "@/lib/waveform-edit"
import {
  MAX_PX_PER_SEC,
  clampPxPerSec,
  clampScrollSec,
  fitPxPerSec,
  zoomAtX,
  type Viewport,
} from "@/lib/waveform-viewport"
import type { Clip } from "@/lib/workspace-clips"

// The waveform editor panel (US-18.1 + US-18.2). Owns the viewport (zoom +
// scroll) and — from US-18.2 — the region selection, the in-app clipboard, and
// the edited audio. Playback state is borrowed from the shared player store.
//
// Edits (cut / delete / paste) splice the decoded samples directly, so the
// canvas renders the *real* edited waveform with no operation-stack replay. They
// are non-destructive: the original `audio` prop is untouched; the edit lives in
// `edited` state and the `operations` log is the handoff seam for save (US-18.4).
//
// The stored viewport is the user's *intent* (absolute px/sec + scrollSec); the
// effective viewport is derived + clamped against the measured width each
// render, so a resize — or an edit that changes the duration — self-corrects.

const CANVAS_HEIGHT = 160
const BUTTON_ZOOM_FACTOR = 1.6

export function WaveformEditor({
  clip,
  audio,
}: {
  clip: Clip
  audio: ClipAudio
}) {
  const { state, dispatch } = usePlayer()

  // The audio actually shown/edited. Starts as the decoded prop; cut/paste/delete
  // replace it. ClipEditor keys this subtree by clip id, so it resets per clip.
  const [edited, setEdited] = useState<ClipAudio>(audio)
  const [selection, setSelection] = useState<Region | null>(null)
  const [clipboard, setClipboard] = useState<Float32Array | null>(null)
  const [operations, setOperations] = useState<EditOperation[]>([])

  const duration = edited.duration

  // Load this clip into the player so the playhead + seek reuse the real audio
  // engine. Async dispatch (not synchronous setState), only on clip change.
  useEffect(() => {
    if (state.current?.id !== clip.id) {
      dispatch({ type: "load", tracks: [trackFromClip(clip)] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.id])

  const isCurrent = state.current?.id === clip.id
  const playheadSec = isCurrent ? state.currentTime : 0

  // Measure the available width; the viewport is expressed in px/sec, so every
  // zoom/scroll bound depends on it. ResizeObserver keeps it responsive.
  const containerRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  // Stored intent (null = "use the fit overview"); the effective viewport below
  // is always derived and clamped to the current width.
  const [intent, setIntent] = useState<Viewport | null>(null)

  const ready = width > 0 && duration > 0
  const fitPx = ready ? fitPxPerSec(duration, width) : 1
  const vp: Viewport | null = !ready
    ? null
    : intent
      ? (() => {
          const pxPerSec = clampPxPerSec(intent.pxPerSec, duration, width)
          return {
            pxPerSec,
            scrollSec: clampScrollSec(intent.scrollSec, duration, pxPerSec, width),
          }
        })()
      : { pxPerSec: fitPx, scrollSec: 0 }

  const zoomAt = (nextPx: number, anchorX: number) => {
    if (vp) setIntent(zoomAtX(vp, nextPx, anchorX, duration, width))
  }
  const scrollTo = (scrollSec: number) => {
    if (vp) setIntent({ ...vp, scrollSec })
  }
  const seek = (sec: number) => {
    dispatch({ type: "seek/request", time: Math.max(0, Math.min(duration, sec)) })
  }
  const fit = () => setIntent({ pxPerSec: fitPx, scrollSec: 0 })

  // --- Selection + clipboard (US-18.2) -------------------------------------
  const clampSec = (sec: number) => Math.max(0, Math.min(duration, sec))

  // A clamped, ordered region — or null when it collapses to zero width, so a
  // drag-back-to-origin or a handle dropped on its twin never leaves a 0-length
  // selection that would log no-op cut/delete operations.
  const regionOrNull = (a: number, b: number): Region | null => {
    const r = normalizeRegion(clampSec(a), clampSec(b))
    return r.endSec > r.startSec ? r : null
  }

  // A drag on the canvas sweeps a new selection.
  const select = (a: number, b: number) => setSelection(regionOrNull(a, b))

  // A handle drag moves one edge; re-normalize so start ≤ end if they cross.
  const adjustEdge = (edge: "start" | "end", sec: number) =>
    setSelection((cur) =>
      cur === null
        ? cur
        : edge === "start"
          ? regionOrNull(sec, cur.endSec)
          : regionOrNull(cur.startSec, sec)
    )

  // A bare click (seek) clears the selection, like clicking off it.
  const seekAndClear = (sec: number) => {
    setSelection(null)
    seek(sec)
  }

  const copy = () => {
    if (!selection) return
    setClipboard(sliceRegion(edited, selection.startSec, selection.endSec))
  }

  const removeSelected = (kind: "cut" | "delete") => {
    if (!selection) return
    if (kind === "cut") {
      setClipboard(sliceRegion(edited, selection.startSec, selection.endSec))
    }
    setEdited(removeRegion(edited, selection.startSec, selection.endSec))
    setOperations((ops) => [
      ...ops,
      { kind, startSec: selection.startSec, endSec: selection.endSec },
    ])
    setSelection(null)
  }

  const paste = () => {
    if (!clipboard || clipboard.length === 0) return
    // Clamp into the *current* (possibly already-edited) timeline so the insert
    // point, the logged op, and the seek all agree — playheadSec can sit past
    // the end after a delete shortened the clip.
    const atSec = clampSec(playheadSec)
    const durationSec = clipboard.length / edited.sampleRate
    const next = insertRegion(edited, atSec, clipboard)
    setEdited(next)
    setOperations((ops) => [...ops, { kind: "paste", atSec, durationSec }])
    setSelection(null)
    // Move the playhead to the end of the pasted region, in the NEW timeline.
    dispatch({
      type: "seek/request",
      time: Math.min(next.duration, atSec + durationSec),
    })
  }

  useEditorShortcuts({
    onCut: () => removeSelected("cut"),
    onCopy: copy,
    onPaste: paste,
    onDelete: () => removeSelected("delete"),
  })

  const atMin = !vp || vp.pxPerSec <= fitPx + 1e-6
  const atMax = !!vp && vp.pxPerSec >= MAX_PX_PER_SEC - 1e-6

  return (
    <div
      className="flex flex-col gap-2"
      data-edited-duration={duration.toFixed(3)}
      data-op-count={operations.length}
      data-clipboard-samples={clipboard?.length ?? 0}
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="truncate text-lg font-semibold">
          {clip.title ?? "Untitled clip"}
        </h1>
        <ZoomControls
          onZoomIn={() =>
            zoomAt((vp ? vp.pxPerSec : fitPx) * BUTTON_ZOOM_FACTOR, width / 2)
          }
          onZoomOut={() =>
            zoomAt((vp ? vp.pxPerSec : fitPx) / BUTTON_ZOOM_FACTOR, width / 2)
          }
          onFit={fit}
          atMin={atMin}
          atMax={atMax}
        />
      </div>

      <div
        ref={containerRef}
        className="overflow-hidden rounded-lg border border-border bg-card"
      >
        {vp ? (
          <>
            <TimeRuler viewport={vp} width={width} duration={duration} />
            <div className="relative">
              <WaveformCanvas
                audio={edited}
                viewport={vp}
                width={width}
                height={CANVAS_HEIGHT}
                playheadSec={playheadSec}
                onSeek={seekAndClear}
                onZoom={zoomAt}
                onScrollSec={scrollTo}
                onSelect={select}
              />
              <SelectionOverlay
                selection={selection}
                viewport={vp}
                width={width}
                height={CANVAS_HEIGHT}
                duration={duration}
                onAdjust={adjustEdge}
              />
            </div>
          </>
        ) : (
          <div style={{ height: CANVAS_HEIGHT + 20 }} />
        )}
      </div>

      <div className="flex min-h-4 items-center justify-between gap-2">
        <SelectionInfo selection={selection} />
      </div>

      {vp && (
        <WaveformScrollbar
          viewport={vp}
          width={width}
          duration={duration}
          onScroll={scrollTo}
        />
      )}
    </div>
  )
}
