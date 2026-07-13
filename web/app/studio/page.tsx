"use client"

import { Suspense, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { ZoomInAreaIcon, ZoomOutAreaIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AddTrackButton, TrackLane } from "@/components/studio/TrackLane"
import { Playhead } from "@/components/studio/Playhead"
import { RulerArea } from "@/components/studio/RulerArea"
import { SnapControls } from "@/components/studio/SnapControls"
import { TransportControls } from "@/components/studio/TransportControls"
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel"
import { StudioProvider, useStudio } from "@/contexts/studio-context"
import { useAuth } from "@/hooks/use-auth"
import { useClip } from "@/hooks/use-clip"
import { useRequireAuth } from "@/hooks/use-require-auth"
import { useStudioPlayback } from "@/hooks/use-studio-playback"
import {
  MAX_ZOOM,
  MIN_ZOOM,
  TRACK_STRIP_PX,
  timelineDurationSec,
  zoomToPxPerSec,
} from "@/lib/timeline"
import { BPM_MAX, BPM_MIN, inferTrackType } from "@/lib/track-types"

const ZOOM_BUTTON_FACTOR = 1.5
// Matches the sensitivity used for Ctrl+wheel zoom on the waveform canvas.
const WHEEL_ZOOM_SENSITIVITY = 0.002

/** Preloads the ?song= clip onto a fresh track at 0s (US-19.1). Preloads
 * again for any clip id not already preloaded this session — e.g. a
 * client-side nav from ?song=A to ?song=B, or back again to A — but never
 * re-preloads a clip id it's already added a track for. */
function useSongPreload() {
  const searchParams = useSearchParams()
  const songId = searchParams.get("song") ?? undefined
  const { clip } = useClip(songId)
  const { dispatch } = useStudio()
  const preloadedRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!clip || preloadedRef.current.has(clip.id)) return
    preloadedRef.current.add(clip.id)
    const trackId = crypto.randomUUID()
    // The preloaded track takes the clip's own type (US-19.2), so the clip is
    // guaranteed to land on it.
    dispatch({
      type: "ADD_TRACK",
      id: trackId,
      trackType: inferTrackType(clip.generation_mode),
    })
    dispatch({
      type: "ADD_CLIP",
      id: crypto.randomUUID(),
      trackId,
      clipId: clip.id,
      startSec: 0,
      title: clip.title,
      durationSec: clip.duration,
      generationMode: clip.generation_mode,
      clipBpm: clip.bpm,
    })
  }, [clip, dispatch])
}

/** Project tempo control (US-19.2): drafts locally while typing, commits a
 * clamped SET_BPM on blur/Enter — mirrors TrackLane's rename commit pattern. */
function TempoInput() {
  const { state, dispatch } = useStudio()
  const [draft, setDraft] = useState<string | null>(null)

  function commit() {
    // Number("") === 0, so an emptied field would otherwise commit SET_BPM 0
    // and clamp the project to BPM_MIN — treat blank as "revert" instead.
    if (draft !== null && draft.trim() !== "") {
      const bpm = Number(draft)
      if (Number.isFinite(bpm)) dispatch({ type: "SET_BPM", bpm })
    }
    setDraft(null)
  }

  return (
    <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
      BPM
      <Input
        type="number"
        aria-label="Project tempo (BPM)"
        min={BPM_MIN}
        max={BPM_MAX}
        value={draft ?? state.bpm}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur()
        }}
        className="h-8 w-20"
      />
    </label>
  )
}

function StudioHeader() {
  const { state, dispatch } = useStudio()
  return (
    <div className="flex items-center justify-between gap-2 border-b border-border p-4">
      <h1 className="text-2xl font-semibold">Studio</h1>
      <div className="flex items-center gap-2">
        <TransportControls />
        <TempoInput />
        <SnapControls />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => dispatch({ type: "TOGGLE_DISPLAY_MODE" })}
        >
          {state.displayMode === "bars-beats" ? "Bars/Beats" : "mm:ss"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="Zoom out"
          disabled={state.zoom <= MIN_ZOOM + 1e-6}
          onClick={() =>
            dispatch({
              type: "SET_ZOOM",
              zoom: state.zoom / ZOOM_BUTTON_FACTOR,
            })
          }
        >
          <HugeiconsIcon icon={ZoomOutAreaIcon} />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="Zoom in"
          disabled={state.zoom >= MAX_ZOOM - 1e-6}
          onClick={() =>
            dispatch({
              type: "SET_ZOOM",
              zoom: state.zoom * ZOOM_BUTTON_FACTOR,
            })
          }
        >
          <HugeiconsIcon icon={ZoomInAreaIcon} />
        </Button>
      </div>
    </div>
  )
}

function StudioTimeline() {
  const { state, dispatch } = useStudio()
  const { accessToken } = useAuth()
  useStudioPlayback(accessToken)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Latest zoom read through a ref so the non-passive wheel listener (needed
  // to preventDefault on Ctrl/Cmd+wheel) attaches once instead of on every
  // zoom tick — mirrors components/editor/WaveformCanvas.tsx.
  const zoomRef = useRef(state.zoom)
  useEffect(() => {
    zoomRef.current = state.zoom
  }, [state.zoom])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    function onWheel(e: WheelEvent) {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const factor = Math.exp(-e.deltaY * WHEEL_ZOOM_SENSITIVITY)
      dispatch({ type: "SET_ZOOM", zoom: zoomRef.current * factor })
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [dispatch])

  const pxPerSec = zoomToPxPerSec(state.zoom)
  const allPlacements = useMemo(
    () => state.tracks.flatMap((t) => t.clips),
    [state.tracks]
  )
  const durationSec = timelineDurationSec(allPlacements)

  return (
    <div ref={scrollRef} className="flex-1 overflow-x-auto overflow-y-auto">
      <div className="relative">
        {/* Ruler ticks must start where each lane's timeline region does —
            after its control strip — so a spacer of the same width sits in
            front of it (TrackLane's own strip uses the same constant). */}
        <div className="flex">
          <div
            data-testid="ruler-spacer"
            className="shrink-0"
            style={{ width: TRACK_STRIP_PX }}
          />
          <RulerArea pxPerSec={pxPerSec} durationSec={durationSec} />
        </div>
        {state.tracks.map((track) => (
          <TrackLane
            key={track.id}
            track={track}
            pxPerSec={pxPerSec}
            token={accessToken}
          />
        ))}
        <Playhead playheadSec={state.playheadSec} pxPerSec={pxPerSec} />
      </div>
      <div className="p-2">
        <AddTrackButton />
      </div>
    </div>
  )
}

function StudioView() {
  useSongPreload()
  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <StudioHeader />
        <StudioTimeline />
      </div>
      {/* Clip library, dragged onto lanes to add clips (US-19.1). Hidden below
          lg to keep the timeline usable at the minimum supported width,
          mirroring the app shell's RightPanel (see app/create/page.tsx). */}
      <aside
        aria-label="Clip library"
        className="hidden w-80 shrink-0 flex-col border-l border-border p-4 lg:flex"
      >
        <WorkspacePanel />
      </aside>
    </div>
  )
}

function StudioPageContent() {
  const { isLoading, isAuthenticated } = useRequireAuth()
  // ponytail: render nothing until authed — useRequireAuth redirects otherwise,
  // mirrors app/create/page.tsx.
  if (isLoading || !isAuthenticated) return null
  return (
    <StudioProvider>
      <StudioView />
    </StudioProvider>
  )
}

export default function StudioPage() {
  // useSearchParams (inside useSongPreload) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <StudioPageContent />
    </Suspense>
  )
}
