"use client"

import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react"

import {
  clamp,
  COMPRESSOR_ATTACK_SEC_MAX,
  COMPRESSOR_ATTACK_SEC_MIN,
  COMPRESSOR_RATIO_MAX,
  COMPRESSOR_RATIO_MIN,
  COMPRESSOR_RELEASE_SEC_MAX,
  COMPRESSOR_RELEASE_SEC_MIN,
  COMPRESSOR_THRESHOLD_DB_MAX,
  COMPRESSOR_THRESHOLD_DB_MIN,
  DEFAULT_MASTER_BUS,
  EQ_GAIN_DB_MAX,
  EQ_GAIN_DB_MIN,
  EQ_HIGH_SHELF_FREQ_MAX,
  EQ_HIGH_SHELF_FREQ_MIN,
  EQ_LOW_SHELF_FREQ_MAX,
  EQ_LOW_SHELF_FREQ_MIN,
  EQ_MID_FREQ_MAX,
  EQ_MID_FREQ_MIN,
  EQ_Q_MAX,
  EQ_Q_MIN,
  LIMITER_CEILING_DB_MAX,
  LIMITER_CEILING_DB_MIN,
  MASTER_VOLUME_DB_MAX,
  MASTER_VOLUME_DB_MIN,
  type MasterBusState,
} from "@/lib/master-bus"
import {
  clampZoom,
  DEFAULT_BPM,
  type DisplayMode,
  type Placement,
  type SnapResolution,
} from "@/lib/timeline"
import { VOLUME_DB_MAX, VOLUME_DB_MIN } from "@/lib/track-audio"
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
  /** Fader level in dB, [-60, +6]; -60 renders as -∞ / silence (US-19.4). */
  volumeDb: number
  /** Stereo position, [-100, +100] mapping to StereoPannerNode -1..1 (US-19.4). */
  pan: number
  muted: boolean
  solo: boolean
  clips: Placement[]
}

/** A named flag on the time ruler labeling a song section (US-19.3). */
export type StudioMarker = {
  id: string
  sec: number
  label: string
}

export type StudioState = {
  tracks: StudioTrack[]
  playheadSec: number
  isPlaying: boolean
  zoom: number
  displayMode: DisplayMode
  /** Project tempo — loop-track clips stretch to match it (US-19.2). */
  bpm: number
  /** Snap-to-grid (US-19.3): quantize clip drops/markers to beat divisions. */
  snapEnabled: boolean
  snapResolution: SnapResolution
  /** Loop region (US-19.3): playback repeats [loopStartSec, loopEndSec). */
  loopEnabled: boolean
  loopStartSec: number
  loopEndSec: number
  markers: StudioMarker[]
  // Bumped by user-initiated SEEKs and effective BPM changes (never by the
  // rAF loop's own SET_PLAYHEAD ticks) — the playback engine watches this to
  // reschedule audio from the new position/rates instead of stomping it on
  // the next frame.
  seekEpoch: number
  /** Master bus: EQ/compressor/limiter/volume sitting after the track sum,
   * before the destination (US-19.5). */
  masterBus: MasterBusState
}

export const initialStudioState: StudioState = {
  tracks: [],
  playheadSec: 0,
  isPlaying: false,
  zoom: 1,
  displayMode: "bars-beats",
  bpm: DEFAULT_BPM,
  snapEnabled: true,
  snapResolution: "1beat",
  loopEnabled: false,
  loopStartSec: 0,
  // 4 bars at the default 120 BPM — a sensible starting loop.
  loopEndSec: 8,
  markers: [],
  seekEpoch: 0,
  masterBus: DEFAULT_MASTER_BUS,
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
  | { type: "SET_TRACK_VOLUME"; trackId: string; volumeDb: number }
  | { type: "SET_TRACK_PAN"; trackId: string; pan: number }
  | { type: "TOGGLE_TRACK_MUTE"; trackId: string }
  | { type: "TOGGLE_TRACK_SOLO"; trackId: string }
  | { type: "SET_TRACK_COLOR"; trackId: string; color: string }
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
  | { type: "TOGGLE_SNAP" }
  | { type: "SET_SNAP_RESOLUTION"; resolution: SnapResolution }
  | { type: "TOGGLE_LOOP" }
  | { type: "SET_LOOP_REGION"; startSec: number; endSec: number }
  | { type: "ADD_MARKER"; id: string; sec: number; label: string }
  | { type: "RENAME_MARKER"; markerId: string; label: string }
  | { type: "MOVE_MARKER"; markerId: string; sec: number }
  | { type: "DELETE_MARKER"; markerId: string }
  | { type: "SET_MASTER_VOLUME"; volumeDb: number }
  | {
      type: "SET_MASTER_EQ"
      band: "low" | "mid" | "high"
      freqHz?: number
      gainDb?: number
      /** Only meaningful for the mid band's peaking filter. */
      q?: number
    }
  | {
      type: "SET_MASTER_COMPRESSOR"
      thresholdDb?: number
      ratio?: number
      attackSec?: number
      releaseSec?: number
    }
  | { type: "SET_MASTER_LIMITER_CEILING"; ceilingDb: number }

/** Replace one track via `update`; unknown ids are a strict no-op. */
function updateTrack(
  state: StudioState,
  trackId: string,
  update: (t: StudioTrack) => StudioTrack
): StudioState {
  if (!state.tracks.some((t) => t.id === trackId)) return state
  return {
    ...state,
    tracks: state.tracks.map((t) => (t.id === trackId ? update(t) : t)),
  }
}

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
        volumeDb: 0,
        pan: 0,
        muted: false,
        solo: false,
        clips: [],
      }
      return { ...state, tracks: [...state.tracks, track] }
    }
    case "REMOVE_TRACK":
      return {
        ...state,
        tracks: state.tracks.filter((t) => t.id !== action.trackId),
      }
    case "RENAME_TRACK":
      return updateTrack(state, action.trackId, (t) => ({
        ...t,
        name: action.name,
      }))
    case "SET_TRACK_VOLUME": {
      if (!Number.isFinite(action.volumeDb)) return state
      const volumeDb = Math.min(
        VOLUME_DB_MAX,
        Math.max(VOLUME_DB_MIN, action.volumeDb)
      )
      return updateTrack(state, action.trackId, (t) => ({ ...t, volumeDb }))
    }
    case "SET_TRACK_PAN": {
      if (!Number.isFinite(action.pan)) return state
      const pan = Math.min(100, Math.max(-100, action.pan))
      return updateTrack(state, action.trackId, (t) => ({ ...t, pan }))
    }
    case "TOGGLE_TRACK_MUTE":
      return updateTrack(state, action.trackId, (t) => ({
        ...t,
        muted: !t.muted,
      }))
    case "TOGGLE_TRACK_SOLO":
      return updateTrack(state, action.trackId, (t) => ({
        ...t,
        solo: !t.solo,
      }))
    case "SET_TRACK_COLOR": {
      // Applied verbatim as CSS (border/background) — an empty value would
      // silently erase the track's visual identity.
      const color = action.color.trim()
      if (!color) return state
      return updateTrack(state, action.trackId, (t) => ({ ...t, color }))
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
      const bpm = Math.min(BPM_MAX, Math.max(BPM_MIN, action.bpm))
      // No-op commits (same value, or clamped into the same value) must not
      // bump seekEpoch — that would audibly restart an in-flight playback.
      if (bpm === state.bpm) return state
      return {
        ...state,
        bpm,
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
    case "TOGGLE_SNAP":
      return { ...state, snapEnabled: !state.snapEnabled }
    case "SET_SNAP_RESOLUTION":
      return { ...state, snapResolution: action.resolution }
    case "TOGGLE_LOOP":
      return { ...state, loopEnabled: !state.loopEnabled }
    case "SET_LOOP_REGION": {
      // Handles can cross during a drag — store the normalized range.
      const a = Math.max(0, action.startSec)
      const b = Math.max(0, action.endSec)
      return {
        ...state,
        loopStartSec: Math.min(a, b),
        loopEndSec: Math.max(a, b),
      }
    }
    case "ADD_MARKER":
      return {
        ...state,
        markers: [
          ...state.markers,
          { id: action.id, sec: Math.max(0, action.sec), label: action.label },
        ],
      }
    case "RENAME_MARKER": {
      if (!state.markers.some((m) => m.id === action.markerId)) return state
      return {
        ...state,
        markers: state.markers.map((m) =>
          m.id === action.markerId ? { ...m, label: action.label } : m
        ),
      }
    }
    case "MOVE_MARKER":
      return {
        ...state,
        markers: state.markers.map((m) =>
          m.id === action.markerId ? { ...m, sec: Math.max(0, action.sec) } : m
        ),
      }
    case "DELETE_MARKER":
      return {
        ...state,
        markers: state.markers.filter((m) => m.id !== action.markerId),
      }
    case "SET_MASTER_VOLUME": {
      if (!Number.isFinite(action.volumeDb)) return state
      return {
        ...state,
        masterBus: {
          ...state.masterBus,
          masterVolumeDb: clamp(
            action.volumeDb,
            MASTER_VOLUME_DB_MIN,
            MASTER_VOLUME_DB_MAX
          ),
        },
      }
    }
    case "SET_MASTER_EQ": {
      const { band, freqHz, gainDb, q } = action
      // No fields → keep state identity (same rationale as SET_BPM).
      if (freqHz === undefined && gainDb === undefined && q === undefined) {
        return state
      }
      if (
        (freqHz !== undefined && !Number.isFinite(freqHz)) ||
        (gainDb !== undefined && !Number.isFinite(gainDb)) ||
        (q !== undefined && !Number.isFinite(q))
      ) {
        return state
      }
      const eq = state.masterBus.eq
      if (band === "low") {
        return {
          ...state,
          masterBus: {
            ...state.masterBus,
            eq: {
              ...eq,
              lowShelf: {
                freqHz:
                  freqHz !== undefined
                    ? clamp(
                        freqHz,
                        EQ_LOW_SHELF_FREQ_MIN,
                        EQ_LOW_SHELF_FREQ_MAX
                      )
                    : eq.lowShelf.freqHz,
                gainDb:
                  gainDb !== undefined
                    ? clamp(gainDb, EQ_GAIN_DB_MIN, EQ_GAIN_DB_MAX)
                    : eq.lowShelf.gainDb,
              },
            },
          },
        }
      }
      if (band === "mid") {
        return {
          ...state,
          masterBus: {
            ...state.masterBus,
            eq: {
              ...eq,
              midPeak: {
                freqHz:
                  freqHz !== undefined
                    ? clamp(freqHz, EQ_MID_FREQ_MIN, EQ_MID_FREQ_MAX)
                    : eq.midPeak.freqHz,
                gainDb:
                  gainDb !== undefined
                    ? clamp(gainDb, EQ_GAIN_DB_MIN, EQ_GAIN_DB_MAX)
                    : eq.midPeak.gainDb,
                q:
                  q !== undefined ? clamp(q, EQ_Q_MIN, EQ_Q_MAX) : eq.midPeak.q,
              },
            },
          },
        }
      }
      return {
        ...state,
        masterBus: {
          ...state.masterBus,
          eq: {
            ...eq,
            highShelf: {
              freqHz:
                freqHz !== undefined
                  ? clamp(
                      freqHz,
                      EQ_HIGH_SHELF_FREQ_MIN,
                      EQ_HIGH_SHELF_FREQ_MAX
                    )
                  : eq.highShelf.freqHz,
              gainDb:
                gainDb !== undefined
                  ? clamp(gainDb, EQ_GAIN_DB_MIN, EQ_GAIN_DB_MAX)
                  : eq.highShelf.gainDb,
            },
          },
        },
      }
    }
    case "SET_MASTER_COMPRESSOR": {
      const { thresholdDb, ratio, attackSec, releaseSec } = action
      if (
        (thresholdDb !== undefined && !Number.isFinite(thresholdDb)) ||
        (ratio !== undefined && !Number.isFinite(ratio)) ||
        (attackSec !== undefined && !Number.isFinite(attackSec)) ||
        (releaseSec !== undefined && !Number.isFinite(releaseSec))
      ) {
        return state
      }
      const compressor = state.masterBus.compressor
      return {
        ...state,
        masterBus: {
          ...state.masterBus,
          compressor: {
            thresholdDb:
              thresholdDb !== undefined
                ? clamp(
                    thresholdDb,
                    COMPRESSOR_THRESHOLD_DB_MIN,
                    COMPRESSOR_THRESHOLD_DB_MAX
                  )
                : compressor.thresholdDb,
            ratio:
              ratio !== undefined
                ? clamp(ratio, COMPRESSOR_RATIO_MIN, COMPRESSOR_RATIO_MAX)
                : compressor.ratio,
            attackSec:
              attackSec !== undefined
                ? clamp(
                    attackSec,
                    COMPRESSOR_ATTACK_SEC_MIN,
                    COMPRESSOR_ATTACK_SEC_MAX
                  )
                : compressor.attackSec,
            releaseSec:
              releaseSec !== undefined
                ? clamp(
                    releaseSec,
                    COMPRESSOR_RELEASE_SEC_MIN,
                    COMPRESSOR_RELEASE_SEC_MAX
                  )
                : compressor.releaseSec,
          },
        },
      }
    }
    case "SET_MASTER_LIMITER_CEILING": {
      if (!Number.isFinite(action.ceilingDb)) return state
      return {
        ...state,
        masterBus: {
          ...state.masterBus,
          limiterCeilingDb: clamp(
            action.ceilingDb,
            LIMITER_CEILING_DB_MIN,
            LIMITER_CEILING_DB_MAX
          ),
        },
      }
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
