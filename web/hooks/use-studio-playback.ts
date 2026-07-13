"use client"

import { useEffect, useRef } from "react"

import { usePlayer } from "@/contexts/player-context"
import { useStudio } from "@/contexts/studio-context"
import { getClipAudio } from "@/lib/clip-audio-cache"
import { computePlaybackSchedule, type Placement } from "@/lib/timeline"

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

type ActiveSource = { source: AudioBufferSourceNode }

export function useStudioPlayback(token: string | null): void {
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

  function ensureContext(): AudioContext {
    if (!ctxRef.current) {
      const Ctx =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext
      const ctx = new Ctx()
      ctxRef.current = ctx
      const gain = ctx.createGain()
      gain.connect(ctx.destination)
      masterGainRef.current = gain
    }
    return ctxRef.current
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
    const master = masterGainRef.current!
    const placements: Placement[] = state.tracks.flatMap((t) => t.clips)
    const schedule = computePlaybackSchedule(
      placements,
      state.playheadSec,
      ctx.currentTime
    )

    let cancelled = false
    Promise.all(
      schedule.map(async (item) => {
        const audio = await getClipAudio(item.clipId, token)
        return { ...item, buffer: audio.buffer }
      })
    ).then((scheduled) => {
      if (cancelled) return
      for (const item of scheduled) {
        const source = ctx.createBufferSource()
        source.buffer = item.buffer
        source.connect(master)
        source.start(item.when, item.offset)
        sourcesRef.current.push({ source })
      }
    })

    originRef.current = {
      ctxTime: ctx.currentTime,
      playheadSec: state.playheadSec,
    }
    function tick() {
      const origin = originRef.current
      if (!ctxRef.current || !origin) return
      const elapsed = ctxRef.current.currentTime - origin.ctxTime
      dispatch({ type: "SET_PLAYHEAD", sec: origin.playheadSec + elapsed })
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

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
}
