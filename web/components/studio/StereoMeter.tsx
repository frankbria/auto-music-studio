"use client"

import { useEffect, useRef, useState, type RefObject } from "react"

import {
  METER_FLOOR_DB,
  peakDbfs,
  rmsDbfs,
  stepPeakHold,
  type PeakHoldState,
} from "@/lib/metering"
import { cn } from "@/lib/utils"

// Real-time peak/RMS metering for the master bus (US-19.5): a rAF loop reads
// both analysers' time-domain data each frame, computes levels via the pure
// math in lib/metering.ts, and setState's the result — setState here runs
// inside the rAF callback (an async-context callback), not synchronously in
// the effect body, so it doesn't trip react-hooks/set-state-in-effect.

const METER_TICKS_DB = [0, -6, -12, -24, -48] as const

function dbToPercent(db: number): number {
  const clamped = Math.max(METER_FLOOR_DB, Math.min(0, db))
  return ((clamped - METER_FLOOR_DB) / -METER_FLOOR_DB) * 100
}

function levelColorClass(db: number): string {
  if (db > 0) return "bg-destructive"
  if (db > -6) return "bg-amber-500"
  return "bg-emerald-500"
}

type ChannelLevels = { peakDb: number; rmsDb: number; holdDb: number }

const SILENT_LEVELS: ChannelLevels = {
  peakDb: METER_FLOOR_DB,
  rmsDb: METER_FLOOR_DB,
  holdDb: METER_FLOOR_DB,
}

function ChannelBar({
  label,
  levels,
}: {
  label: "L" | "R"
  levels: ChannelLevels
}) {
  const clipping = levels.peakDb > 0
  return (
    <div className="flex flex-col items-center gap-1">
      <div
        role="meter"
        aria-label={`${label} channel level`}
        aria-valuemin={METER_FLOOR_DB}
        aria-valuemax={0}
        aria-valuenow={Math.round(Math.min(0, levels.peakDb))}
        className="relative h-32 w-3 overflow-hidden rounded-sm bg-muted"
      >
        <div
          className={cn(
            "absolute inset-x-0 bottom-0",
            levelColorClass(levels.rmsDb)
          )}
          style={{ height: `${dbToPercent(levels.rmsDb)}%` }}
        />
        <div
          data-role="peak-hold"
          className={cn(
            "absolute inset-x-0 h-0.5",
            levelColorClass(levels.holdDb)
          )}
          style={{ bottom: `${dbToPercent(levels.holdDb)}%` }}
        />
      </div>
      <span
        data-testid={`clip-indicator-${label.toLowerCase()}`}
        data-clipping={clipping}
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          clipping ? "bg-destructive" : "bg-muted"
        )}
      />
    </div>
  )
}

export function StereoMeter({
  analyserLeft,
  analyserRight,
}: {
  analyserLeft: RefObject<AnalyserNode | null>
  analyserRight: RefObject<AnalyserNode | null>
}) {
  const [left, setLeft] = useState<ChannelLevels>(SILENT_LEVELS)
  const [right, setRight] = useState<ChannelLevels>(SILENT_LEVELS)

  const leftHoldRef = useRef<PeakHoldState | null>(null)
  const rightHoldRef = useRef<PeakHoldState | null>(null)
  const buffersRef = useRef(
    new WeakMap<AnalyserNode, Float32Array<ArrayBuffer>>()
  )
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    function bufferFor(analyser: AnalyserNode): Float32Array<ArrayBuffer> {
      const cached = buffersRef.current.get(analyser)
      if (cached && cached.length === analyser.fftSize) return cached
      const fresh = new Float32Array(analyser.fftSize)
      buffersRef.current.set(analyser, fresh)
      return fresh
    }

    function readChannel(
      analyser: AnalyserNode | null,
      holdRef: RefObject<PeakHoldState | null>,
      nowMs: number
    ): ChannelLevels {
      if (!analyser) return SILENT_LEVELS
      const buffer = bufferFor(analyser)
      analyser.getFloatTimeDomainData(buffer)
      const peakDb = peakDbfs(buffer)
      const rmsDb = rmsDbfs(buffer)
      holdRef.current = stepPeakHold(holdRef.current, peakDb, nowMs)
      return { peakDb, rmsDb, holdDb: holdRef.current.db }
    }

    // Returning the previous object when levels are unchanged lets React
    // bail out of the re-render — during silence/pause the loop keeps
    // ticking but stops repainting.
    function replaceIfChanged(prev: ChannelLevels, next: ChannelLevels) {
      return prev.peakDb === next.peakDb &&
        prev.rmsDb === next.rmsDb &&
        prev.holdDb === next.holdDb
        ? prev
        : next
    }

    function tick(nowMs: number) {
      const nextLeft = readChannel(analyserLeft.current, leftHoldRef, nowMs)
      const nextRight = readChannel(analyserRight.current, rightHoldRef, nowMs)
      setLeft((prev) => replaceIfChanged(prev, nextLeft))
      setRight((prev) => replaceIfChanged(prev, nextRight))
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [analyserLeft, analyserRight])

  return (
    <div className="flex items-end gap-3">
      <div className="relative h-32 w-5 text-[10px] text-muted-foreground">
        {METER_TICKS_DB.map((db) => (
          <span
            key={db}
            className="absolute right-0 -translate-y-1/2 tabular-nums"
            style={{ bottom: `${dbToPercent(db)}%` }}
          >
            {db}
          </span>
        ))}
      </div>
      <ChannelBar label="L" levels={left} />
      <ChannelBar label="R" levels={right} />
    </div>
  )
}
