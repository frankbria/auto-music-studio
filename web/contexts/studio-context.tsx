"use client"

import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react"

import { clampZoom, DEFAULT_BPM, type DisplayMode, type Placement } from "@/lib/timeline"
import {
  BPM_MAX,
  BPM_MIN,
  TRACK_TYPES,
  inferTrackType,
  type TrackType,
} from "@/lib/track-types"

export type StudioTrack = {
  id: string
  name: string
  /** Which clip category this track accepts (US-19.2). */
  trackType: TrackType
  color: string
  clips: Placement[]
}

export type StudioState = {
  tracks: StudioTrack[]
  playheadSec: number
  isPlaying: boolean
  zoom: number
  displayMode: DisplayMode
  /** Project tempo — loop-track clips stretch to match it (US-19.2). */
  bpm: number
  // Bumped only by a user-initiated SEEK (never by the rAF loop's own
  // SET_PLAYHEAD ticks) — the playback engine watches this to reschedule
  // audio from the new position instead of stomping it on the next frame.
  seekEpoch: number
}

export const initialStudioState: StudioState = {
  tracks: [],
  playheadSec: 0,
  isPlaying: false,
  zoom: 1,
  displayMode: "bars-beats",
  bpm: DEFAULT_BPM,
  seekEpoch: 0,
}

export type StudioAction =
  | {
      type: "ADD_TRACK"
      id: string
      trackType: TrackType
      name?: string
      color?: string
    }
  | { type: "REMOVE_TRACK"; trackId: string }
  | { type: "RENAME_TRACK"; trackId: string; name: string }
  | {
      type: "ADD_CLIP"
      id: string
      trackId: string
      clipId: string
      startSec: number
      title: string | null
      durationSec: number | null
      /** For track-type matching; undefined/null infers as AI-generated. */
      generationMode?: string | null
      /** For loop-track tempo inheritance. */
      clipBpm?: number | null
    }
  | {
      type: "MOVE_CLIP"
      trackId: string
      placementId: string
      startSec: number
    }
  | { type: "SET_PLAYHEAD"; sec: number }
  | { type: "SEEK"; sec: number }
  | { type: "SET_PLAYING"; playing: boolean }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "SET_BPM"; bpm: number }
  | { type: "TOGGLE_DISPLAY_MODE" }

export function studioReducer(
  state: StudioState,
  action: StudioAction
): StudioState {
  switch (action.type) {
    case "ADD_TRACK": {
      const track: StudioTrack = {
        id: action.id,
        name: action.name ?? `Track ${state.tracks.length + 1}`,
        trackType: action.trackType,
        // Type color by default — the type IS the visual identity (US-19.2).
        color: action.color ?? TRACK_TYPES[action.trackType].color,
        clips: [],
      }
      return { ...state, tracks: [...state.tracks, track] }
    }
    case "REMOVE_TRACK":
      return {
        ...state,
        tracks: state.tracks.filter((t) => t.id !== action.trackId),
      }
    case "RENAME_TRACK": {
      if (!state.tracks.some((t) => t.id === action.trackId)) return state
      return {
        ...state,
        tracks: state.tracks.map((t) =>
          t.id === action.trackId ? { ...t, name: action.name } : t
        ),
      }
    }
    case "ADD_CLIP": {
      const track = state.tracks.find((t) => t.id === action.trackId)
      if (!track) return state
      // Strict type matching (US-19.2): a clip only lands on a track of its
      // inferred type. The drop target gives visual feedback during the drag;
      // this is the authoritative check.
      if (inferTrackType(action.generationMode) !== track.trackType) {
        return state
      }
      const placement: Placement = {
        id: action.id,
        clipId: action.clipId,
        startSec: action.startSec,
        title: action.title,
        durationSec: action.durationSec,
        clipBpm: action.clipBpm ?? null,
      }
      return {
        ...state,
        tracks: state.tracks.map((t) =>
          t.id === action.trackId ? { ...t, clips: [...t.clips, placement] } : t
        ),
      }
    }
    case "MOVE_CLIP": {
      const dest = state.tracks.find((t) => t.id === action.trackId)
      if (!dest) return state
      const source = state.tracks.find((t) =>
        t.clips.some((c) => c.id === action.placementId)
      )
      const original = source?.clips.find((c) => c.id === action.placementId)
      if (!source || !original) return state
      // A clip was validated against its track's type on entry, so same-type
      // moves are always safe; cross-type moves are rejected (US-19.2).
      if (source.trackType !== dest.trackType) return state
      const relocated: Placement = {
        ...original,
        startSec: Math.max(0, action.startSec),
      }
      return {
        ...state,
        tracks: state.tracks.map((t) => {
          const isSource = t.id === source.id
          const isDest = t.id === action.trackId
          if (!isSource && !isDest) return t
          let clips = t.clips
          if (isSource) clips = clips.filter((c) => c.id !== action.placementId)
          if (isDest) clips = [...clips, relocated]
          return { ...t, clips }
        }),
      }
    }
    case "SET_PLAYHEAD":
      return { ...state, playheadSec: Math.max(0, action.sec) }
    case "SEEK":
      return {
        ...state,
        playheadSec: Math.max(0, action.sec),
        seekEpoch: state.seekEpoch + 1,
      }
    case "SET_PLAYING":
      return { ...state, isPlaying: action.playing }
    case "SET_ZOOM":
      return { ...state, zoom: clampZoom(action.zoom) }
    case "SET_BPM": {
      if (!Number.isFinite(action.bpm)) return state
      return {
        ...state,
        bpm: Math.min(BPM_MAX, Math.max(BPM_MIN, action.bpm)),
        // A tempo change re-rates loop-track clips; treat it like a seek so a
        // playback already in flight reschedules its sources at the new rates
        // (the engine only watches isPlaying/seekEpoch).
        seekEpoch: state.seekEpoch + 1,
      }
    }
    case "TOGGLE_DISPLAY_MODE":
      return {
        ...state,
        displayMode:
          state.displayMode === "bars-beats" ? "mm-ss" : "bars-beats",
      }
    default:
      return state
  }
}

type StudioContextValue = {
  state: StudioState
  dispatch: React.Dispatch<StudioAction>
}

export const StudioContext = createContext<StudioContextValue | null>(null)

export function StudioProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(studioReducer, initialStudioState)
  const value = useMemo(() => ({ state, dispatch }), [state])
  return (
    <StudioContext.Provider value={value}>{children}</StudioContext.Provider>
  )
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext)
  if (!ctx) throw new Error("useStudio must be used within a StudioProvider")
  return ctx
}
