"use client"

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react"

import type { Track } from "@/lib/clips"

export type RepeatMode = "off" | "all" | "one"

export type PlayerState = {
  current: Track | null
  /** Upcoming tracks (index 0 plays next). */
  queue: Track[]
  /** Previously played, most-recent last; powers "previous". */
  history: Track[]
  isPlaying: boolean
  currentTime: number
  duration: number
  isLoading: boolean
  error: string | null
  volume: number
  isMuted: boolean
  /** Volume to restore when unmuting. */
  previousVolume: number
  repeatMode: RepeatMode
  shuffle: boolean
  isQueueOpen: boolean
  likedIds: string[]
  /** Set by a scrub; the audio engine seeks to it then dispatches "seek/done". */
  seekRequest: number | null
}

export const initialPlayerState: PlayerState = {
  current: null,
  queue: [],
  history: [],
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  isLoading: false,
  error: null,
  volume: 0.8,
  isMuted: false,
  previousVolume: 0.8,
  repeatMode: "off",
  shuffle: false,
  isQueueOpen: false,
  likedIds: [],
  seekRequest: null,
}

export type PlayerAction =
  | { type: "play/track"; track: Track }
  | { type: "play/queue"; tracks: Track[]; startIndex?: number }
  | { type: "load"; tracks: Track[] }
  | { type: "play" }
  | { type: "pause" }
  | { type: "toggle" }
  | { type: "time/set"; time: number }
  | { type: "duration/set"; duration: number }
  | { type: "loading/set"; loading: boolean }
  | { type: "error/set"; error: string | null }
  | { type: "seek/request"; time: number }
  | { type: "seek/done" }
  | { type: "volume/set"; volume: number }
  | { type: "mute/toggle" }
  | { type: "next" }
  | { type: "previous" }
  | { type: "ended" }
  | { type: "queue/add"; track: Track }
  | { type: "queue/addNext"; track: Track }
  | { type: "queue/remove"; index: number }
  | { type: "queue/reorder"; from: number; to: number }
  | { type: "queue/clear" }
  | { type: "queue/panel"; open?: boolean }
  | { type: "repeat/cycle" }
  | { type: "shuffle/toggle" }
  | { type: "like/toggle"; id: string }

const clampVolume = (v: number) => Math.min(1, Math.max(0, v))

/** Pick the index of the next track to play from a queue, honoring shuffle. */
function nextIndex(queueLength: number, shuffle: boolean): number {
  if (queueLength === 0) return -1
  if (!shuffle) return 0
  return Math.floor(Math.random() * queueLength)
}

/** Start playing `track`, pushing the outgoing current onto history. */
function startTrack(
  state: PlayerState,
  track: Track,
  queue: Track[]
): PlayerState {
  return {
    ...state,
    history: state.current ? [...state.history, state.current] : state.history,
    current: track,
    queue,
    currentTime: 0,
    duration: 0,
    isPlaying: true,
    isLoading: true,
    error: null,
    seekRequest: null,
  }
}

/** Advance to the next track; used by both "next" and natural "ended". */
function advance(state: PlayerState): PlayerState {
  const idx = nextIndex(state.queue.length, state.shuffle)
  if (idx >= 0) {
    const track = state.queue[idx]
    const queue = state.queue.filter((_, i) => i !== idx)
    return startTrack(state, track, queue)
  }
  // Queue empty. Repeat-all rebuilds the played history into a fresh queue.
  if (
    state.repeatMode === "all" &&
    (state.history.length > 0 || state.current)
  ) {
    const all = [...state.history, ...(state.current ? [state.current] : [])]
    const [first, ...rest] = all
    return {
      ...state,
      history: [],
      current: first,
      queue: rest,
      currentTime: 0,
      duration: 0,
      isPlaying: true,
      isLoading: true,
      error: null,
      seekRequest: null,
    }
  }
  // Nothing left to play.
  return { ...state, isPlaying: false, currentTime: state.duration }
}

export function playerReducer(
  state: PlayerState,
  action: PlayerAction
): PlayerState {
  switch (action.type) {
    case "play/track":
      return startTrack(state, action.track, state.queue)
    case "play/queue": {
      const start = action.startIndex ?? 0
      const track = action.tracks[start]
      if (!track) return state
      const queue = action.tracks.filter((_, i) => i !== start)
      return startTrack(state, track, queue)
    }
    case "load": {
      // Stage a queue without auto-playing (seed / restore). No user gesture
      // yet, so autoplay would be blocked anyway.
      const [first, ...rest] = action.tracks
      if (!first) return state
      return {
        ...state,
        current: first,
        queue: rest,
        history: [],
        currentTime: 0,
        duration: first.duration ?? 0,
        isPlaying: false,
        isLoading: false,
      }
    }
    case "play":
      return state.current ? { ...state, isPlaying: true } : state
    case "pause":
      return { ...state, isPlaying: false }
    case "toggle":
      return state.current ? { ...state, isPlaying: !state.isPlaying } : state
    case "time/set":
      return { ...state, currentTime: action.time }
    case "duration/set":
      return { ...state, duration: action.duration }
    case "loading/set":
      return { ...state, isLoading: action.loading }
    case "error/set":
      return {
        ...state,
        error: action.error,
        isLoading: false,
        isPlaying: false,
      }
    case "seek/request":
      return { ...state, seekRequest: action.time, currentTime: action.time }
    case "seek/done":
      return { ...state, seekRequest: null }
    case "volume/set": {
      const volume = clampVolume(action.volume)
      // Adjusting volume above zero implicitly unmutes.
      return { ...state, volume, isMuted: volume === 0 ? state.isMuted : false }
    }
    case "mute/toggle":
      return state.isMuted
        ? { ...state, isMuted: false, volume: state.previousVolume ?? 0.8 }
        : { ...state, isMuted: true, previousVolume: state.volume }
    case "next":
      return advance(state)
    case "previous": {
      // Restart current if we're past the first few seconds, else step back.
      // Preserve play/pause — stepping tracks shouldn't force playback to start.
      if (state.currentTime > 3 || state.history.length === 0) {
        return { ...state, currentTime: 0, seekRequest: 0 }
      }
      const prev = state.history[state.history.length - 1]
      return {
        ...state,
        history: state.history.slice(0, -1),
        current: prev,
        queue: state.current ? [state.current, ...state.queue] : state.queue,
        currentTime: 0,
        duration: 0,
        isLoading: true,
        seekRequest: null,
      }
    }
    case "ended":
      if (state.repeatMode === "one" && state.current) {
        return { ...state, currentTime: 0, seekRequest: 0, isPlaying: true }
      }
      return advance(state)
    case "queue/add":
      return { ...state, queue: [...state.queue, action.track] }
    case "queue/addNext":
      return { ...state, queue: [action.track, ...state.queue] }
    case "queue/remove":
      return {
        ...state,
        queue: state.queue.filter((_, i) => i !== action.index),
      }
    case "queue/reorder": {
      const { from, to } = action
      if (
        from === to ||
        from < 0 ||
        to < 0 ||
        from >= state.queue.length ||
        to >= state.queue.length
      ) {
        return state
      }
      const queue = [...state.queue]
      const [moved] = queue.splice(from, 1)
      queue.splice(to, 0, moved)
      return { ...state, queue }
    }
    case "queue/clear":
      return { ...state, queue: [] }
    case "queue/panel":
      return { ...state, isQueueOpen: action.open ?? !state.isQueueOpen }
    case "repeat/cycle": {
      const order: RepeatMode[] = ["off", "all", "one"]
      const next = order[(order.indexOf(state.repeatMode) + 1) % order.length]
      return { ...state, repeatMode: next }
    }
    case "shuffle/toggle":
      return { ...state, shuffle: !state.shuffle }
    case "like/toggle":
      return {
        ...state,
        likedIds: state.likedIds.includes(action.id)
          ? state.likedIds.filter((id) => id !== action.id)
          : [...state.likedIds, action.id],
      }
    default:
      return state
  }
}

// --- Persistence -----------------------------------------------------------

const STORAGE_KEY = "ams.player.v1"
type Persisted = Pick<
  PlayerState,
  | "volume"
  | "isMuted"
  | "previousVolume"
  | "repeatMode"
  | "shuffle"
  | "likedIds"
>

function loadPersisted(): Partial<PlayerState> {
  if (typeof window === "undefined") return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const p = JSON.parse(raw) as Partial<Persisted>
    return p
  } catch {
    return {}
  }
}

// --- Context ---------------------------------------------------------------

type PlayerContextValue = {
  state: PlayerState
  dispatch: React.Dispatch<PlayerAction>
}

export const PlayerContext = createContext<PlayerContextValue | null>(null)

export function PlayerProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(
    playerReducer,
    initialPlayerState,
    (init) => ({ ...init, ...loadPersisted() })
  )

  // Persist the durable preference slice (not transient playback position).
  useEffect(() => {
    if (typeof window === "undefined") return
    const persisted: Persisted = {
      volume: state.volume,
      isMuted: state.isMuted,
      previousVolume: state.previousVolume,
      repeatMode: state.repeatMode,
      shuffle: state.shuffle,
      likedIds: state.likedIds,
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted))
    } catch {
      // Private mode / quota — non-fatal, preferences just won't persist.
    }
  }, [
    state.volume,
    state.isMuted,
    state.previousVolume,
    state.repeatMode,
    state.shuffle,
    state.likedIds,
  ])

  const value = useMemo(() => ({ state, dispatch }), [state])
  return (
    <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
  )
}

export function usePlayer(): PlayerContextValue {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error("usePlayer must be used within a PlayerProvider")
  return ctx
}
