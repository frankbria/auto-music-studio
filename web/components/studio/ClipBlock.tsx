"use client"

import { useEffect, useRef, useState, type DragEvent } from "react"

import { getClipAudio } from "@/lib/clip-audio-cache"
import { setClipDragData } from "@/lib/clip-drag"
import type { Placement } from "@/lib/timeline"

// A clip placed on a Studio track lane (US-19.1). Positioned/sized purely from
// startSec/durationSec × pxPerSec; the waveform thumbnail draws the cached
// peak downsample onto a canvas, guarding a null 2D context the same way
// components/editor/WaveformCanvas.tsx does (jsdom's getContext returns null).
// Draggable to reposition: dragging it sets a "move" payload naming its own
// placement id that a TrackLane's drop handler turns into a MOVE_CLIP, same or
// different lane either way — the reducer finds the source track itself, so
// the payload doesn't need to name it.

const THUMBNAIL_HEIGHT = 32

export function ClipBlock({
  placement,
  pxPerSec,
  color,
  token,
}: {
  placement: Placement
  pxPerSec: number
  color: string
  token: string | null
}) {
  const left = placement.startSec * pxPerSec
  const width = Math.max(1, (placement.durationSec ?? 0) * pxPerSec)

  const [peaks, setPeaks] = useState<Float32Array | null>(null)
  useEffect(() => {
    if (!token) return
    let active = true
    getClipAudio(placement.clipId, token)
      .then((audio) => {
        if (active) setPeaks(audio.peaks)
      })
      .catch(() => {
        // Thumbnail stays blank on a decode failure — not fatal to the placement.
      })
    return () => {
      active = false
    }
  }, [placement.clipId, token])

  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !peaks || width <= 0) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.floor(width * dpr)
    canvas.height = Math.floor(THUMBNAIL_HEIGHT * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, THUMBNAIL_HEIGHT)

    ctx.fillStyle = "rgba(255,255,255,0.8)"
    const mid = THUMBNAIL_HEIGHT / 2
    const barWidth = Math.max(1, width / peaks.length)
    for (let i = 0; i < peaks.length; i++) {
      const barH = Math.max(1, peaks[i] * mid)
      ctx.fillRect(i * barWidth, mid - barH, barWidth, barH * 2)
    }
  }, [peaks, width])

  const title = placement.title ?? "Untitled clip"

  function onDragStart(e: DragEvent<HTMLDivElement>) {
    setClipDragData(e.dataTransfer, { kind: "move", placementId: placement.id })
  }

  return (
    <div
      data-testid="clip-block"
      draggable
      onDragStart={onDragStart}
      className="absolute top-1 flex cursor-grab flex-col overflow-hidden rounded-md text-white shadow-sm active:cursor-grabbing"
      style={{ left, width, backgroundColor: color }}
      title={title}
    >
      <span className="truncate px-1.5 py-0.5 text-[11px] font-medium">
        {title}
      </span>
      <canvas ref={canvasRef} style={{ width, height: THUMBNAIL_HEIGHT }} />
    </div>
  )
}
