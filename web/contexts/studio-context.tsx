"use client"

import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react"

import { clampZoom, type DisplayMode, type Placement } from "@/lib/timeline"

export type StudioTrack = {
  id: string
  name: string
  color: string
  clips: Placement[]
}

export type StudioState = {
  tracks: StudioTrack[]
  playheadSec: number
  isPlaying: boolean
  zoom: number
  displayMode: DisplayMode
}

export const initialStudioState: StudioState = {
  tracks: [],
  playheadSec: 0,
  isPlaying: false,
  zoom: 1,
  displayMode: "bars-beats",
}

// Distinct per-track colors (plan requirement), cycled by track index.
const TRACK_COLORS = [
  "#6d28d9",
  "#0ea5e9",
  "#f97316",
  "#22c55e",
  "#ec4899",
  "#eab308",
]

export type StudioAction =
  | { type: "ADD_TRACK"; id: string; name?: string; color?: string }
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
    }
  | {
      type: "MOVE_CLIP"
      trackId: string
      placementId: string
      startSec: number
    }
  | { type: "SET_PLAYHEAD"; sec: number }
  | { type: "SET_PLAYING"; playing: boolean }
  | { type: "SET_ZOOM"; zoom: number }
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
        color:
          action.color ??
          TRACK_COLORS[state.tracks.length % TRACK_COLORS.length],
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
      const placement: Placement = {
        id: action.id,
        clipId: action.clipId,
        startSec: action.startSec,
        title: action.title,
        durationSec: action.durationSec,
      }
      return {
        ...state,
        tracks: state.tracks.map((t) =>
          t.id === action.trackId ? { ...t, clips: [...t.clips, placement] } : t
        ),
      }
    }
    case "MOVE_CLIP": {
      const source = state.tracks.find((t) =>
        t.clips.some((c) => c.id === action.placementId)
      )
      const original = source?.clips.find((c) => c.id === action.placementId)
      if (!source || !original) return state
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
    case "SET_PLAYING":
      return { ...state, isPlaying: action.playing }
    case "SET_ZOOM":
      return { ...state, zoom: clampZoom(action.zoom) }
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
