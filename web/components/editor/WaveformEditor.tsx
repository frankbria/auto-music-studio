"use client"

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"

import { HugeiconsIcon } from "@hugeicons/react"
import { FloppyDiskIcon } from "@hugeicons/core-free-icons"

import { EditToolbar } from "@/components/editor/EditToolbar"
import { RepaintPanel } from "@/components/editor/RepaintPanel"
import { SaveVersionModal } from "@/components/editor/SaveVersionModal"
import { SelectionInfo } from "@/components/editor/SelectionInfo"
import { SelectionOverlay } from "@/components/editor/SelectionOverlay"
import { TimeRuler } from "@/components/editor/TimeRuler"
import { UndoRedoControls } from "@/components/editor/UndoRedoControls"
import { WaveformCanvas } from "@/components/editor/WaveformCanvas"
import { WaveformScrollbar } from "@/components/editor/WaveformScrollbar"
import { ZoomControls } from "@/components/editor/ZoomControls"
import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { useEditorShortcuts } from "@/hooks/use-editor-shortcuts"
import type { ClipAudio } from "@/lib/audio-peaks"
import { trackFromClip } from "@/lib/clips"
import {
  applyCrossfade,
  applyFadeIn,
  applyFadeOut,
  applyGain,
  applyNormalize,
  applySilence,
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
// Edits (cut / delete / paste / fade / gain / …) splice or transform the decoded
// samples directly, so the canvas renders the *real* edited waveform with no
// operation-stack replay. They are non-destructive: the original `audio` prop is
// untouched; each edit produces a fresh ClipAudio pushed onto the undo/redo
// history (US-18.4), and the per-snapshot operation log is the handoff seam for
// "Save as new version".
//
// The stored viewport is the user's *intent* (absolute px/sec + scrollSec); the
// effective viewport is derived + clamped against the measured width each
// render, so a resize — or an edit that changes the duration — self-corrects.

const CANVAS_HEIGHT = 160
const BUTTON_ZOOM_FACTOR = 1.6

// One point in the edit timeline: the audio at that point plus the operation
// that produced it (null for the pristine original at index 0).
type Snapshot = { audio: ClipAudio; op: EditOperation | null }
type EditHistory = { snapshots: Snapshot[]; cursor: number }

export function WaveformEditor({
  clip,
  audio,
}: {
  clip: Clip
  audio: ClipAudio
}) {
  const { state, dispatch } = usePlayer()

  // Undo/redo history (US-18.4). Each edit is a pure, non-destructive
  // ClipAudio→ClipAudio transform, so the edited buffer *is* a complete
  // snapshot — history is a stack of snapshots + a cursor, no command replay.
  // snapshots[0] is the untouched decoded prop, so undoing to the start restores
  // the original and the source clip is never mutated. ClipEditor keys this
  // subtree by clip id, so the whole stack resets per clip.
  // ponytail: the stack is unbounded per the "unlimited undo" spec; each entry
  // holds one full buffer, so memory grows with edit count — add a drop-oldest
  // cap if a long-clip session ever pressures memory.
  const [history, setHistory] = useState<EditHistory>(() => ({
    snapshots: [{ audio, op: null }],
    cursor: 0,
  }))
  const [selection, setSelection] = useState<Region | null>(null)
  const [clipboard, setClipboard] = useState<Float32Array | null>(null)
  // Pending gain (dB) while the Gain popover is open — drives a live, throwaway
  // waveform preview; null when nothing is being previewed. (US-18.3)
  const [gainPreview, setGainPreview] = useState<number | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)

  const { snapshots, cursor } = history
  const edited = snapshots[cursor].audio
  const canUndo = cursor > 0
  const canRedo = cursor < snapshots.length - 1
  const isDirty = cursor > 0
  // The operations applied to reach the current snapshot (index 0 is pristine),
  // in order — what "Save as new version" ships as provenance.
  const operations = useMemo(
    () => snapshots.slice(1, cursor + 1).map((s) => s.op as EditOperation),
    [snapshots, cursor]
  )

  const duration = edited.duration

  // --- Undo/redo history (US-18.4) -----------------------------------------
  // Apply an edit: drop any redo tail, push the new snapshot, advance the
  // cursor. Every edit routes through here, so undo/redo covers them uniformly.
  // The selection is cleared because the buffer changed under it (the old code
  // cleared it per-op).
  const pushEdit = (nextAudio: ClipAudio, op: EditOperation) => {
    setHistory((h) => {
      const kept = h.snapshots.slice(0, h.cursor + 1)
      return { snapshots: [...kept, { audio: nextAudio, op }], cursor: kept.length }
    })
    setSelection(null)
  }
  const undo = () => {
    setHistory((h) => (h.cursor > 0 ? { ...h, cursor: h.cursor - 1 } : h))
    setSelection(null)
    setGainPreview(null)
  }
  const redo = () => {
    setHistory((h) =>
      h.cursor < h.snapshots.length - 1 ? { ...h, cursor: h.cursor + 1 } : h
    )
    setSelection(null)
    setGainPreview(null)
  }

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
    pushEdit(removeRegion(edited, selection.startSec, selection.endSec), {
      kind,
      startSec: selection.startSec,
      endSec: selection.endSec,
    })
  }

  const paste = () => {
    if (!clipboard || clipboard.length === 0) return
    // Clamp into the *current* (possibly already-edited) timeline so the insert
    // point, the logged op, and the seek all agree — playheadSec can sit past
    // the end after a delete shortened the clip.
    const atSec = clampSec(playheadSec)
    const durationSec = clipboard.length / edited.sampleRate
    const next = insertRegion(edited, atSec, clipboard)
    pushEdit(next, { kind: "paste", atSec, durationSec })
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
    onUndo: undo,
    onRedo: redo,
  })

  // --- Processing ops (US-18.3) --------------------------------------------
  // Commit an amplitude transform through the undo/redo history (US-18.4). The
  // selection clear happens in pushEdit — deliberate for every op, since the
  // buffer changed and the old selection's coordinates are stale (crossfade
  // included, which is playhead-based and ignores the selection).
  const commit = (next: ClipAudio, op: EditOperation) => pushEdit(next, op)

  const fadeIn = () => {
    if (!selection) return
    const { startSec, endSec } = selection
    commit(applyFadeIn(edited, startSec, endSec), { kind: "fade-in", startSec, endSec })
  }
  const fadeOut = () => {
    if (!selection) return
    const { startSec, endSec } = selection
    commit(applyFadeOut(edited, startSec, endSec), { kind: "fade-out", startSec, endSec })
  }
  const silence = () => {
    if (!selection) return
    const { startSec, endSec } = selection
    commit(applySilence(edited, startSec, endSec), { kind: "silence", startSec, endSec })
  }
  const gain = (gainDb: number) => {
    if (!selection) return
    const { startSec, endSec } = selection
    commit(applyGain(edited, startSec, endSec, gainDb), {
      kind: "gain",
      startSec,
      endSec,
      gainDb,
    })
  }
  // Normalize the selection, or the whole clip when nothing is selected.
  const normalize = () => {
    const startSec = selection?.startSec ?? 0
    const endSec = selection?.endSec ?? duration
    commit(applyNormalize(edited, startSec, endSec, 0), {
      kind: "normalize",
      startSec,
      endSec,
      targetDb: 0,
    })
  }
  // Crossfade at the current playhead (clamped inside the transform). Skip the
  // commit when the window can't fit (playhead at the very start/end), so a
  // no-op never logs a ghost op into the US-18.4 save seam.
  const crossfade = (durationSec: number) => {
    const next = applyCrossfade(edited, playheadSec, durationSec)
    if (next.mono.length === edited.mono.length) return
    commit(next, { kind: "crossfade", positionSec: playheadSec, durationSec })
  }

  // The audio shown on the canvas: while a gain preview is live, apply it to the
  // selection so the pending change is visible before Apply. Memoized so the
  // buffer copy only runs when the preview or audio actually changes — not on
  // every unrelated re-render while the Gain popover is open.
  const shown = useMemo(
    () =>
      gainPreview !== null && selection
        ? applyGain(edited, selection.startSec, selection.endSec, gainPreview)
        : edited,
    [edited, selection, gainPreview]
  )

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
        <div className="flex items-center gap-2">
          <UndoRedoControls
            onUndo={undo}
            onRedo={redo}
            canUndo={canUndo}
            canRedo={canRedo}
          />
          <Button
            type="button"
            size="sm"
            onClick={() => setSaveOpen(true)}
            disabled={!isDirty}
          >
            <HugeiconsIcon icon={FloppyDiskIcon} data-icon="inline-start" />
            Save as new version
          </Button>
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
      </div>

      <EditToolbar
        hasSelection={selection !== null}
        onFadeIn={fadeIn}
        onFadeOut={fadeOut}
        onSilence={silence}
        onNormalize={normalize}
        onGainPreview={setGainPreview}
        onGainApply={gain}
        onCrossfade={crossfade}
      />

      <div
        ref={containerRef}
        className="overflow-hidden rounded-lg border border-border bg-card"
      >
        {vp ? (
          <>
            <TimeRuler viewport={vp} width={width} duration={duration} />
            <div className="relative">
              <WaveformCanvas
                audio={shown}
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

      {/* Repaint mode (US-18.5): a live selection unlocks AI section-regenerate.
          The backend returns a full crossfade-blended child clip; we decode it
          and push it through the same undo stack as every other edit. */}
      {selection && (
        <RepaintPanel
          selection={selection}
          clipId={clip.id}
          onRepainted={(nextAudio, op) => pushEdit(nextAudio, op)}
        />
      )}

      {vp && (
        <WaveformScrollbar
          viewport={vp}
          width={width}
          duration={duration}
          onScroll={scrollTo}
        />
      )}

      <SaveVersionModal
        clipId={clip.id}
        audio={edited}
        operations={operations}
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
      />
    </div>
  )
}
