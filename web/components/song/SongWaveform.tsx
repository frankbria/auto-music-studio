"use client"

import { useEffect, useMemo, useRef } from "react"

import { usePlayer } from "@/contexts/player-context"
import { WAVEFORM_BARS as BARS, barHeights } from "@/lib/waveform"

// Detail-page waveform (US-17.1). Unlike the player's MiniWaveform — which is
// always bound to the *current* track — this is seeded by an explicit `clipId`
// so it renders the right shape for the song on the page even before playback
// starts. Click-to-seek only acts when this clip is the one playing (otherwise
// there is no playhead to move).

export function SongWaveform({ clipId }: { clipId: string }) {
  const { state, dispatch } = usePlayer()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const isCurrent = state.current?.id === clipId
  const progress =
    isCurrent && state.duration > 0 ? state.currentTime / state.duration : 0
  // Pure function of clipId — memoize so it isn't recomputed on every audio
  // tick (progress changes ~4Hz during playback, but the bars never do).
  const heights = useMemo(() => barHeights(clipId), [clipId])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const hgt = canvas.clientHeight
    canvas.width = w * dpr
    canvas.height = hgt * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, w, hgt)

    const styles = getComputedStyle(canvas)
    const played = styles.getPropertyValue("--primary").trim() || "#888"
    const unplayed =
      styles.getPropertyValue("--muted-foreground").trim() || "#ccc"

    const gap = 2
    const barW = (w - gap * (BARS - 1)) / BARS
    for (let i = 0; i < BARS; i++) {
      const bh = heights[i] * hgt
      ctx.fillStyle = i / BARS < progress ? played : unplayed
      ctx.globalAlpha = i / BARS < progress ? 0.9 : 0.4
      ctx.fillRect(i * (barW + gap), (hgt - bh) / 2, barW, bh)
    }
  }, [heights, progress])

  function seekFromClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!isCurrent || state.duration <= 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    dispatch({ type: "seek/request", time: ratio * state.duration })
  }

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label="Waveform"
      onClick={seekFromClick}
      className="h-16 w-full cursor-pointer"
    />
  )
}
