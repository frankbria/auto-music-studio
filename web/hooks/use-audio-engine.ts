"use client"

import { useEffect, useRef } from "react"

import { usePlayer } from "@/contexts/player-context"

/**
 * Owns the single HTML5 <audio> element and keeps it in sync with the player
 * store. Mounted exactly once (at the shell level) so playback survives route
 * changes — the element never remounts. State flows store → audio (src, play,
 * pause, volume, seek); events flow audio → store (time, duration, ended, error).
 */
export function useAudioEngine(): void {
  const { state, dispatch } = usePlayer()
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // Create the single element once and wire event listeners that feed the store.
  useEffect(() => {
    const audio = new Audio()
    audioRef.current = audio
    const onTime = () => dispatch({ type: "time/set", time: audio.currentTime })
    const onLoaded = () => {
      dispatch({ type: "duration/set", duration: audio.duration })
      dispatch({ type: "loading/set", loading: false })
    }
    const onEnded = () => dispatch({ type: "ended" })
    const onError = () =>
      dispatch({ type: "error/set", error: "Playback failed." })
    const onWaiting = () => dispatch({ type: "loading/set", loading: true })
    const onPlaying = () => dispatch({ type: "loading/set", loading: false })

    audio.addEventListener("timeupdate", onTime)
    audio.addEventListener("loadedmetadata", onLoaded)
    audio.addEventListener("durationchange", onLoaded)
    audio.addEventListener("ended", onEnded)
    audio.addEventListener("error", onError)
    audio.addEventListener("waiting", onWaiting)
    audio.addEventListener("playing", onPlaying)
    return () => {
      audio.removeEventListener("timeupdate", onTime)
      audio.removeEventListener("loadedmetadata", onLoaded)
      audio.removeEventListener("durationchange", onLoaded)
      audio.removeEventListener("ended", onEnded)
      audio.removeEventListener("error", onError)
      audio.removeEventListener("waiting", onWaiting)
      audio.removeEventListener("playing", onPlaying)
      audio.pause()
      audioRef.current = null
    }
  }, [dispatch])

  // (Re)load and restart whenever the *track* changes — keyed on id, not src,
  // so advancing between tracks that share an audio URL still restarts from 0
  // (the demo queue reuses one sample). Autoplay only if already playing.
  const trackId = state.current?.id ?? ""
  const src = state.current?.audioUrl ?? ""
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (!src) {
      audio.removeAttribute("src")
      audio.load()
      return
    }
    audio.src = src
    audio.load()
    audio.currentTime = 0
    if (state.isPlaying) audio.play().catch(() => dispatch({ type: "pause" }))
    // Intentionally keyed on the track id only; the play/pause effect below
    // handles isPlaying transitions that aren't track changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackId])

  // Reflect a play/pause toggle that isn't a track change. play() may reject
  // under autoplay policy (no user gesture) → fall back to paused state.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !src) return
    if (state.isPlaying) {
      if (audio.paused) audio.play().catch(() => dispatch({ type: "pause" }))
    } else {
      audio.pause()
    }
  }, [state.isPlaying, src, dispatch])

  // Mirror volume / mute onto the element.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.volume = state.isMuted ? 0 : state.volume
  }, [state.volume, state.isMuted])

  // Honor a scrub request, then clear it. A seek to 0 is also how repeat-one /
  // same-source repeat restart after `ended` — the element is paused at the end,
  // so resume playback if we're meant to be playing.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || state.seekRequest === null) return
    audio.currentTime = state.seekRequest
    if (state.isPlaying && audio.paused) {
      audio.play().catch(() => dispatch({ type: "pause" }))
    }
    dispatch({ type: "seek/done" })
  }, [state.seekRequest, state.isPlaying, dispatch])
}
