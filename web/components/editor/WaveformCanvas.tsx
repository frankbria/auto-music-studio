"use client"

import { useEffect, useMemo, useRef } from "react"

import type { ClipAudio } from "@/lib/audio-peaks"
import { columnPeaks } from "@/lib/audio-peaks"
import { secToX, xToSec, type Viewport } from "@/lib/waveform-viewport"

// The waveform drawing + input surface (US-18.1). Virtual-scrolled: the canvas
// is only ever `width` px wide and re-buckets peaks for the visible sample
// window each render, so it stays accurate from full-clip overview to
// sample-level zoom without a giant off-screen canvas. Input maps to callbacks
// the editor turns into viewport/seek changes:
//   click        → seek        drag           → select a region (US-18.2)
//   Ctrl+wheel   → zoom        wheel/trackpad → horizontal scroll
//   two-finger pinch → zoom (touch)
// Panning moved to the wheel/trackpad + scrollbar when US-18.2 made this an
// editor: plain drag now sweeps out a selection (DAW convention).
// Latest props are read through refs so the non-passive wheel listener (needed
// to preventDefault) attaches once instead of on every zoom tick.

const DRAG_THRESHOLD_PX = 4
const WHEEL_ZOOM_SENSITIVITY = 0.002

export function WaveformCanvas({
  audio,
  viewport,
  width,
  height,
  playheadSec,
  onSeek,
  onZoom,
  onScrollSec,
  onSelect,
}: {
  audio: ClipAudio
  viewport: Viewport
  width: number
  height: number
  playheadSec: number
  onSeek: (sec: number) => void
  onZoom: (nextPx: number, anchorX: number) => void
  onScrollSec: (sec: number) => void
  /** A drag swept a region: both times in seconds (start may be > end mid-drag). */
  onSelect: (startSec: number, endSec: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Refs mirror the latest values for the imperative wheel/pointer handlers,
  // updated in effects (never during render) so the native wheel listener can
  // attach once yet always read fresh state.
  const vpRef = useRef(viewport)
  const cbRef = useRef({ onSeek, onZoom, onScrollSec, onSelect })
  useEffect(() => {
    vpRef.current = viewport
  }, [viewport])
  useEffect(() => {
    cbRef.current = { onSeek, onZoom, onScrollSec, onSelect }
  }, [onSeek, onZoom, onScrollSec, onSelect])

  // Re-bucket peaks only when the audio or the visible window changes — NOT on
  // every playhead tick (~4Hz during playback), which would rescan millions of
  // samples just to move the cursor line. The draw effect below reruns each
  // tick, but only to repaint the (cheap) bars + cursor from this cached array.
  const peaks = useMemo(() => {
    if (width <= 0) return new Float32Array(0)
    const columns = Math.max(1, Math.floor(width))
    const visibleSec = width / viewport.pxPerSec
    const startSample = viewport.scrollSec * audio.sampleRate
    const endSample = (viewport.scrollSec + visibleSec) * audio.sampleRate
    return columnPeaks(audio.mono, startSample, endSample, columns)
  }, [audio, viewport, width])

  // --- Drawing -------------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || width <= 0 || height <= 0) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.floor(width * dpr)
    canvas.height = Math.floor(height * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    const styles = getComputedStyle(canvas)
    const played = styles.getPropertyValue("--primary").trim() || "#6d28d9"
    const unplayed =
      styles.getPropertyValue("--muted-foreground").trim() || "#9ca3af"

    const columns = peaks.length
    const mid = height / 2
    const playheadX = secToX(playheadSec, viewport)
    for (let x = 0; x < columns; x++) {
      const barH = Math.max(1, peaks[x] * mid)
      ctx.fillStyle = x <= playheadX ? played : unplayed
      ctx.globalAlpha = x <= playheadX ? 0.9 : 0.45
      ctx.fillRect(x, mid - barH, 1, barH * 2)
    }

    // Playhead cursor.
    if (playheadX >= 0 && playheadX <= width) {
      ctx.globalAlpha = 1
      ctx.fillStyle = played
      ctx.fillRect(Math.floor(playheadX), 0, 1.5, height)
    }
  }, [peaks, viewport, width, height, playheadSec])

  // --- Pointer input (click / drag / pinch) --------------------------------
  const pointers = useRef(new Map<number, number>()) // pointerId → clientX
  const drag = useRef<{ startX: number; startSec: number; moved: boolean } | null>(
    null
  )
  const pinchDist = useRef<number | null>(null)

  function rectX(clientX: number): number {
    const r = canvasRef.current?.getBoundingClientRect()
    return clientX - (r?.left ?? 0)
  }

  function onPointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    canvasRef.current?.setPointerCapture?.(e.pointerId)
    pointers.current.set(e.pointerId, e.clientX)
    if (pointers.current.size === 1) {
      drag.current = {
        startX: e.clientX,
        startSec: xToSec(rectX(e.clientX), vpRef.current),
        moved: false,
      }
    } else {
      drag.current = null // a second finger cancels the drag/click gesture
    }
  }

  function onPointerMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!pointers.current.has(e.pointerId)) return
    pointers.current.set(e.pointerId, e.clientX)

    if (pointers.current.size >= 2) {
      const xs = [...pointers.current.values()]
      const dist = Math.abs(xs[0] - xs[1])
      const midX = rectX((xs[0] + xs[1]) / 2)
      if (pinchDist.current != null && pinchDist.current > 0 && dist > 0) {
        const ratio = dist / pinchDist.current
        cbRef.current.onZoom(vpRef.current.pxPerSec * ratio, midX)
      }
      pinchDist.current = dist
      return
    }

    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.startX
    if (Math.abs(dx) > DRAG_THRESHOLD_PX) d.moved = true
    if (d.moved) {
      // Sweep out a selection from where the drag began to the pointer now.
      cbRef.current.onSelect(d.startSec, xToSec(rectX(e.clientX), vpRef.current))
    }
  }

  function onPointerUp(e: React.PointerEvent<HTMLCanvasElement>) {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinchDist.current = null
    const d = drag.current
    drag.current = null
    if (d && !d.moved && pointers.current.size === 0) {
      // A tap/click with no pan → seek to the clicked time.
      cbRef.current.onSeek(xToSec(rectX(e.clientX), vpRef.current))
    }
  }

  // --- Wheel (native, non-passive so Ctrl-zoom can preventDefault) ----------
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    function onWheel(e: WheelEvent) {
      const vp = vpRef.current
      const x = rectX(e.clientX)
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const factor = Math.exp(-e.deltaY * WHEEL_ZOOM_SENSITIVITY)
        cbRef.current.onZoom(vp.pxPerSec * factor, x)
      } else {
        e.preventDefault()
        const delta = e.deltaX !== 0 ? e.deltaX : e.deltaY
        cbRef.current.onScrollSec(vp.scrollSec + delta / vp.pxPerSec)
      }
    }
    canvas.addEventListener("wheel", onWheel, { passive: false })
    return () => canvas.removeEventListener("wheel", onWheel)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label="Waveform"
      data-px-per-sec={Math.round(viewport.pxPerSec)}
      data-scroll-sec={viewport.scrollSec.toFixed(3)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      style={{ width, height }}
      className="w-full touch-none cursor-crosshair select-none"
    />
  )
}
