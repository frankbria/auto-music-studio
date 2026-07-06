"use client"

import { useEffect, useLayoutEffect, useRef, useState } from "react"

import { TimeRuler } from "@/components/editor/TimeRuler"
import { WaveformCanvas } from "@/components/editor/WaveformCanvas"
import { WaveformScrollbar } from "@/components/editor/WaveformScrollbar"
import { ZoomControls } from "@/components/editor/ZoomControls"
import { usePlayer } from "@/contexts/player-context"
import type { ClipAudio } from "@/lib/audio-peaks"
import { trackFromClip } from "@/lib/clips"
import {
  MAX_PX_PER_SEC,
  clampPxPerSec,
  clampScrollSec,
  fitPxPerSec,
  zoomAtX,
  type Viewport,
} from "@/lib/waveform-viewport"
import type { Clip } from "@/lib/workspace-clips"

// The waveform editor panel (US-18.1). Owns the viewport (zoom + scroll) and
// wires the canvas / ruler / zoom controls / scrollbar together. Playback state
// is borrowed from the shared player store — entering the editor loads the clip
// as the current track so the playhead follows real playback and click-to-seek
// drives the same <audio> element the Playbar uses (no second audio engine).
//
// The stored viewport is the user's *intent* (absolute px/sec + scrollSec); the
// effective viewport is derived + clamped against the measured width each
// render, so a resize self-corrects without an effect or cascading setState.

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
  const duration = audio.duration

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

  const atMin = !vp || vp.pxPerSec <= fitPx + 1e-6
  const atMax = !!vp && vp.pxPerSec >= MAX_PX_PER_SEC - 1e-6

  return (
    <div className="flex flex-col gap-2">
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
            <WaveformCanvas
              audio={audio}
              viewport={vp}
              width={width}
              height={CANVAS_HEIGHT}
              playheadSec={playheadSec}
              onSeek={seek}
              onZoom={zoomAt}
              onScrollSec={scrollTo}
            />
          </>
        ) : (
          <div style={{ height: CANVAS_HEIGHT + 20 }} />
        )}
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
