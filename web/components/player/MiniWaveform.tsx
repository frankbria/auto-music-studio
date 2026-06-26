"use client"

import { useEffect, useRef } from "react"

import { usePlayer } from "@/contexts/player-context"

const BARS = 64

// ponytail: deterministic pseudo-waveform seeded by track id — looks like a
// mini waveform and shows played/unplayed progress without downloading and
// decoding the whole file. Swap for real peaks (AudioContext.decodeAudioData)
// only if true amplitude rendering is ever required.
function barHeights(seed: string): number[] {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  const out: number[] = []
  for (let i = 0; i < BARS; i++) {
    h ^= h << 13
    h ^= h >>> 17
    h ^= h << 5
    out.push(0.25 + (Math.abs(h) % 1000) / 1000 / 1.4) // 0.25..0.96
  }
  return out
}

/** Canvas mini-waveform with click-to-seek; played bars use the accent color. */
export function MiniWaveform() {
  const { state, dispatch } = usePlayer()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const trackId = state.current?.id ?? ""
  const progress = state.duration > 0 ? state.currentTime / state.duration : 0

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

    const heights = trackId ? barHeights(trackId) : new Array(BARS).fill(0.2)
    const gap = 2
    const barW = (w - gap * (BARS - 1)) / BARS
    for (let i = 0; i < BARS; i++) {
      const bh = heights[i] * hgt
      ctx.fillStyle =
        i / BARS < progress ? `oklch(${played})` : `oklch(${unplayed})`
      ctx.globalAlpha = i / BARS < progress ? 0.9 : 0.4
      ctx.fillRect(i * (barW + gap), (hgt - bh) / 2, barW, bh)
    }
  }, [trackId, progress])

  function seekFromClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!state.current || state.duration <= 0) return
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
      className="h-9 w-full cursor-pointer"
    />
  )
}
