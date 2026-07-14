"use client"

import { useEffect, useRef, type RefObject } from "react"

import { usePlayer } from "@/contexts/player-context"
import { useStudio } from "@/contexts/studio-context"
import { getAudioContextCtor } from "@/lib/audio-context"
import { getClipAudio } from "@/lib/clip-audio-cache"
import {
  LIMITER_ATTACK_SEC,
  LIMITER_RATIO,
  type MasterBusState,
} from "@/lib/master-bus"
import { computePlaybackSchedule, type Placement } from "@/lib/timeline"
import { dbToGain, effectiveTrackGain, panToAudioValue } from "@/lib/track-audio"
import { placementPlaybackRate } from "@/lib/track-types"

// Studio-owned playback engine (US-19.1). Schedules every placement across
// every track through a dedicated AudioContext + master gain node, keyed off
// state.isPlaying; a rAF loop advances SET_PLAYHEAD from ctx.currentTime while
// playing. The global player is a sealed single-<audio> engine with no
// external-source seam (see the plan's "Through the global player" deviation
// note), so starting studio playback instead silences it via a "pause"
// dispatch — the two engines never sound at once.
//
// A user seek mid-playback (contexts/studio-context.tsx's SEEK action) bumps
// seekEpoch instead of just setting playheadSec — SET_PLAYHEAD alone doesn't
// re-trigger this effect, so the rAF loop's stale origin would overwrite the
// seek on its very next frame. Watching seekEpoch makes a seek reschedule the
// whole run from the new position, the same as starting fresh.
//
// Scheduling, the rAF origin, and the tick loop all wait for every clip's
// buffer to finish decoding first — the playhead must not advance (and no
// source should start) until playback can actually begin, or a slow decode
// makes it look like the timeline silently jumped ahead. The schedule itself
// is computed against a ctx.currentTime read *after* decode, not the one at
// effect-start, so scheduled offsets stay correct regardless of how long
// decoding took.

type ActiveSource = { source: AudioBufferSourceNode }

/** One track's live mixer chain: source → gain → panner → master (US-19.4). */
type TrackNodes = { gain: GainNode; panner: StereoPannerNode }

/** The master bus's own post-sum processing chain (US-19.5): sum → EQ →
 * compressor → limiter → masterVolume → [destination, metering splitter]. */
type MasterBusNodes = {
  lowShelf: BiquadFilterNode
  midPeak: BiquadFilterNode
  highShelf: BiquadFilterNode
  compressor: DynamicsCompressorNode
  limiter: DynamicsCompressorNode
  masterVolume: GainNode
}

function applyMasterBusParams(nodes: MasterBusNodes, bus: MasterBusState) {
  nodes.lowShelf.frequency.value = bus.eq.lowShelf.freqHz
  nodes.lowShelf.gain.value = bus.eq.lowShelf.gainDb
  nodes.midPeak.frequency.value = bus.eq.midPeak.freqHz
  nodes.midPeak.gain.value = bus.eq.midPeak.gainDb
  nodes.midPeak.Q.value = bus.eq.midPeak.q
  nodes.highShelf.frequency.value = bus.eq.highShelf.freqHz
  nodes.highShelf.gain.value = bus.eq.highShelf.gainDb
  nodes.compressor.threshold.value = bus.compressor.thresholdDb
  nodes.compressor.ratio.value = bus.compressor.ratio
  nodes.compressor.attack.value = bus.compressor.attackSec
  nodes.compressor.release.value = bus.compressor.releaseSec
  // The limiter's ratio/attack are fixed (a high-ratio DynamicsCompressorNode
  // standing in for a true limiter); only its ceiling is user-adjustable,
  // modeled as the node's threshold.
  nodes.limiter.threshold.value = bus.limiterCeilingDb
  nodes.masterVolume.gain.value = dbToGain(bus.masterVolumeDb)
}

export type MasterAnalysers = {
  analyserLeft: RefObject<AnalyserNode | null>
  analyserRight: RefObject<AnalyserNode | null>
}

export function useStudioPlayback(token: string | null): MasterAnalysers {
  const { state, dispatch } = useStudio()
  const { dispatch: playerDispatch } = usePlayer()

  const ctxRef = useRef<AudioContext | null>(null)
  const masterGainRef = useRef<GainNode | null>(null)
  const sourcesRef = useRef<ActiveSource[]>([])
  const rafRef = useRef<number | null>(null)
  // ctx.currentTime paired with the playhead it started from, at the moment
  // the current play run began — the rAF loop derives playheadSec from this.
  const originRef = useRef<{ ctxTime: number; playheadSec: number } | null>(
    null
  )
  // Loop state mirrored into a ref (US-19.3): the tick loop reads it fresh on
  // every frame without the main effect having to re-run — toggling loop or
  // dragging its handles mid-play must not restart the audio.
  const loopRef = useRef({
    enabled: state.loopEnabled,
    startSec: state.loopStartSec,
    endSec: state.loopEndSec,
  })
  useEffect(() => {
    loopRef.current = {
      enabled: state.loopEnabled,
      startSec: state.loopStartSec,
      endSec: state.loopEndSec,
    }
  }, [state.loopEnabled, state.loopStartSec, state.loopEndSec])

  // Per-track mixer chains (US-19.4), rebuilt on every schedule run. Tracks
  // mirrored into a ref so the scheduling closure reads control values as of
  // decode-complete, not effect-start.
  const trackNodesRef = useRef<Map<string, TrackNodes>>(new Map())
  const tracksRef = useRef(state.tracks)
  // Volume/pan/mute/solo changes retune the live chains directly — they must
  // never enter the scheduling effect's deps, or every fader move would tear
  // down and restart the audio.
  useEffect(() => {
    tracksRef.current = state.tracks
    const anySolo = state.tracks.some((t) => t.solo)
    for (const t of state.tracks) {
      const nodes = trackNodesRef.current.get(t.id)
      if (!nodes) continue
      nodes.gain.gain.value = effectiveTrackGain(t, anySolo)
      nodes.panner.pan.value = panToAudioValue(t.pan)
    }
  }, [state.tracks])

  // The master bus's own chain (US-19.5), built once per AudioContext (see
  // ensureMasterChain below) — unlike per-track nodes, it survives play/pause
  // cycles rather than being rebuilt on every run.
  const masterBusNodesRef = useRef<MasterBusNodes | null>(null)
  const analyserLeftRef = useRef<AnalyserNode | null>(null)
  const analyserRightRef = useRef<AnalyserNode | null>(null)
  // Mirrors state.masterBus (like tracksRef mirrors state.tracks) so a chain
  // built after the user has already tweaked settings still starts in tune.
  const masterBusValuesRef = useRef(state.masterBus)
  useEffect(() => {
    masterBusValuesRef.current = state.masterBus
    const nodes = masterBusNodesRef.current
    if (!nodes) return
    applyMasterBusParams(nodes, state.masterBus)
  }, [state.masterBus])

  function ensureContext(): AudioContext {
    if (!ctxRef.current) {
      const Ctx = getAudioContextCtor()
      const ctx = new Ctx()
      ctxRef.current = ctx
      const gain = ctx.createGain()
      masterGainRef.current = gain
    }
    return ctxRef.current
  }

  /** Builds the master bus's post-sum chain the first time playback runs,
   * splicing it between the summing gain and the destination — see the
   * per-track gain-creation loop below for why this must run *after* it
   * (index ordering the wiring tests key off). Idempotent on every later run. */
  function ensureMasterChain(ctx: AudioContext) {
    if (masterBusNodesRef.current) return
    const sum = masterGainRef.current!

    const lowShelf = ctx.createBiquadFilter()
    lowShelf.type = "lowshelf"
    const midPeak = ctx.createBiquadFilter()
    midPeak.type = "peaking"
    const highShelf = ctx.createBiquadFilter()
    highShelf.type = "highshelf"
    const compressor = ctx.createDynamicsCompressor()
    const limiter = ctx.createDynamicsCompressor()
    limiter.ratio.value = LIMITER_RATIO
    limiter.attack.value = LIMITER_ATTACK_SEC
    const masterVolume = ctx.createGain()
    const splitter = ctx.createChannelSplitter(2)
    const analyserLeft = ctx.createAnalyser()
    const analyserRight = ctx.createAnalyser()

    sum.connect(lowShelf)
    lowShelf.connect(midPeak)
    midPeak.connect(highShelf)
    highShelf.connect(compressor)
    compressor.connect(limiter)
    limiter.connect(masterVolume)
    masterVolume.connect(ctx.destination)
    masterVolume.connect(splitter)
    splitter.connect(analyserLeft, 0)
    splitter.connect(analyserRight, 1)

    const nodes: MasterBusNodes = {
      lowShelf,
      midPeak,
      highShelf,
      compressor,
      limiter,
      masterVolume,
    }
    masterBusNodesRef.current = nodes
    analyserLeftRef.current = analyserLeft
    analyserRightRef.current = analyserRight
    applyMasterBusParams(nodes, masterBusValuesRef.current)
  }

  function stopAllSources() {
    for (const { source } of sourcesRef.current) {
      try {
        source.stop()
      } catch {
        // Already stopped/ended — fine.
      }
      source.disconnect()
    }
    sourcesRef.current = []
    for (const { gain, panner } of trackNodesRef.current.values()) {
      gain.disconnect()
      panner.disconnect()
    }
    trackNodesRef.current.clear()
  }

  function stopTicking() {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }

  useEffect(() => {
    if (!state.isPlaying) {
      stopAllSources()
      stopTicking()
      originRef.current = null
      return
    }
    if (!token) return

    // Idempotent on the very first run (nothing scheduled yet); on a mid-play
    // seek (seekEpoch bump) this tears down the previous run's sources/tick
    // so the reschedule below doesn't double up on top of what's still
    // playing.
    stopAllSources()
    stopTicking()

    // Silence the global playbar — the two playback engines never sound at once.
    playerDispatch({ type: "pause" })

    const ctx = ensureContext()
    // Browsers create an AudioContext "suspended" unless it's constructed
    // synchronously inside a user-gesture handler — ours is created inside an
    // effect, so it needs an explicit resume or playback is silently silent.
    if (ctx.state === "suspended") void ctx.resume()
    const master = masterGainRef.current!
    const placements: Placement[] = state.tracks.flatMap((t) => t.clips)
    // Loop-track clips stretch to the project tempo (US-19.2) — derived here,
    // per placement, from its track's type + the tempo at play time.
    const rateByPlacementId = new Map(
      state.tracks.flatMap((t) =>
        t.clips.map((c) => [
          c.id,
          placementPlaybackRate(c.clipBpm, t.trackType, state.bpm),
        ])
      )
    )
    const trackIdByPlacementId = new Map(
      state.tracks.flatMap((t) => t.clips.map((c) => [c.id, t.id] as const))
    )
    const scheduledTracks = state.tracks
    const playheadAtStart = state.playheadSec

    let cancelled = false
    Promise.all(
      placements.map(
        async (p) =>
          [p.clipId, (await getClipAudio(p.clipId, token)).buffer] as const
      )
    )
      .then((entries) => {
        if (cancelled) return
        const bufferByClipId = new Map(entries)

        // A fresh read of ctx.currentTime here, not the one from before decode
        // — scheduled offsets/times must be relative to "now that we can
        // actually start", not to whenever this effect run began. One snapshot
        // shared with the rAF origin below, so the playhead doesn't
        // permanently trail the audio by however long the scheduling loop
        // took.
        const now = ctx.currentTime
        const schedule = computePlaybackSchedule(
          placements,
          playheadAtStart,
          now,
          (p) => rateByPlacementId.get(p.id) ?? 1
        )

        // One gain → panner chain per track (US-19.4). Control values are read
        // from the live tracks (post-decode), so a fader moved during a slow
        // decode still lands; the live-update effect keeps them tuned after.
        const liveById = new Map(tracksRef.current.map((t) => [t.id, t]))
        const anySolo = tracksRef.current.some((t) => t.solo)
        for (const scheduled of scheduledTracks) {
          const track = liveById.get(scheduled.id) ?? scheduled
          const gain = ctx.createGain()
          gain.gain.value = effectiveTrackGain(track, anySolo)
          const panner = ctx.createStereoPanner()
          panner.pan.value = panToAudioValue(track.pan)
          gain.connect(panner)
          panner.connect(master)
          trackNodesRef.current.set(scheduled.id, { gain, panner })
        }

        // Built after the per-track loop above (see ensureMasterChain's own
        // note) — its GainNode must not shift indices per-track code already
        // assumes for the track chains it just created.
        ensureMasterChain(ctx)

        for (const item of schedule) {
          const buffer = bufferByClipId.get(item.clipId)
          if (!buffer) continue
          const source = ctx.createBufferSource()
          source.buffer = buffer
          source.playbackRate.value = item.playbackRate
          const trackId = trackIdByPlacementId.get(item.placementId)
          const chain = trackId ? trackNodesRef.current.get(trackId) : undefined
          source.connect(chain ? chain.gain : master)
          source.start(item.when, item.offset)
          sourcesRef.current.push({ source })
        }

        originRef.current = {
          ctxTime: now,
          playheadSec: playheadAtStart,
        }
        function tick() {
          const origin = originRef.current
          if (!ctxRef.current || !origin) return
          const elapsed = ctxRef.current.currentTime - origin.ctxTime
          const nextSec = origin.playheadSec + elapsed
          // Loop wrap (US-19.3): crossing the loop end seeks back to its
          // start — SEEK (not SET_PLAYHEAD) so the epoch bump reschedules the
          // audio sources from there, and the new run restarts this loop. A
          // run that began at/past the loop end plays straight through.
          const loop = loopRef.current
          if (
            loop.enabled &&
            loop.endSec > loop.startSec &&
            origin.playheadSec < loop.endSec &&
            nextSec >= loop.endSec
          ) {
            dispatch({ type: "SEEK", sec: loop.startSec })
            return
          }
          dispatch({ type: "SET_PLAYHEAD", sec: nextSec })
          rafRef.current = requestAnimationFrame(tick)
        }
        rafRef.current = requestAnimationFrame(tick)
      })
      .catch(() => {
        // A clip failed to decode (404/500/corrupt) — nothing was scheduled,
        // so leaving isPlaying true would freeze the transport with no
        // feedback. Drop back to stopped; the cache evicts the failed entry,
        // so pressing Play again retries once the clip/server recovers.
        if (cancelled) return
        dispatch({ type: "SET_PLAYING", playing: false })
      })

    return () => {
      cancelled = true
    }
    // Reruns on isPlaying (start/stop) or seekEpoch (a mid-play seek
    // rescheduling from the new position) — state.tracks/state.playheadSec
    // are read fresh each run, not tracked as reactive deps themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.isPlaying, state.seekEpoch])

  // Full teardown on unmount: stop any playing sources and close the context.
  useEffect(() => {
    return () => {
      stopAllSources()
      stopTicking()
      void ctxRef.current?.close()
    }
  }, [])

  // The two ref objects (not their `.current` values) are stable across
  // renders, so this literal's identity churning each render is harmless —
  // a consumer's effect can depend on analyserLeft/analyserRight directly.
  return { analyserLeft: analyserLeftRef, analyserRight: analyserRightRef }
}
