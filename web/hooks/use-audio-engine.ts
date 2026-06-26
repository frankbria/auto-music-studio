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

  // Load a new source whenever the current track changes.
  const src = state.current?.audioUrl ?? ""
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (src) {
      audio.src = src
      audio.load()
    } else {
      audio.removeAttribute("src")
      audio.load()
    }
  }, [src])

  // Reflect play/pause intent. play() may reject under autoplay policy.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !src) return
    if (state.isPlaying) {
      audio.play().catch(() => dispatch({ type: "pause" }))
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

  // Honor a scrub request, then clear it.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || state.seekRequest === null) return
    audio.currentTime = state.seekRequest
    dispatch({ type: "seek/done" })
  }, [state.seekRequest, dispatch])
}
