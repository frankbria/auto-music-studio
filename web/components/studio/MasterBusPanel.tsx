"use client"

import { useEffect, useRef, useState, type RefObject } from "react"

import { Slider } from "@/components/ui/slider"
import { StereoMeter } from "@/components/studio/StereoMeter"
import { useStudio } from "@/contexts/studio-context"
import {
  COMPRESSOR_ATTACK_SEC_MAX,
  COMPRESSOR_ATTACK_SEC_MIN,
  COMPRESSOR_RATIO_MAX,
  COMPRESSOR_RATIO_MIN,
  COMPRESSOR_RELEASE_SEC_MAX,
  COMPRESSOR_RELEASE_SEC_MIN,
  COMPRESSOR_THRESHOLD_DB_MAX,
  COMPRESSOR_THRESHOLD_DB_MIN,
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
} from "@/lib/master-bus"
import { formatVolumeDb } from "@/lib/track-audio"
import { cn } from "@/lib/utils"

// Master bus settings panel (US-19.5): a meter plus four dispatch-only
// sections (volume, EQ, compressor, limiter) — every slider dispatches a
// masterBus action directly, mirroring TrackLane's per-track controls.
// Values/labels come from state.masterBus, never from an AudioNode; the
// limiter-active indicator is the one exception (see LimiterIndicator).

function formatHz(hz: number): string {
  return hz >= 1000 ? `${(hz / 1000).toFixed(1)}kHz` : `${Math.round(hz)}Hz`
}
function formatDb(db: number): string {
  return db > 0 ? `+${db.toFixed(1)}dB` : `${db.toFixed(1)}dB`
}
function formatMs(sec: number): string {
  return `${Math.round(sec * 1000)}ms`
}
function formatRatio(ratio: number): string {
  return `${ratio.toFixed(1)}:1`
}
function formatQ(q: number): string {
  return q.toFixed(1)
}

function LabeledSlider({
  label,
  value,
  min,
  max,
  step,
  format,
  onValueChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  onValueChange: (v: number) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="flex items-center justify-between text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums">{format(value)}</span>
      </span>
      <Slider
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onValueChange(v)}
      />
    </label>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
      {children}
    </h3>
  )
}

/** Polls the live limiter node's `.reduction` (dB of gain currently being
 * pulled) to light an "active" indicator — a genuinely live audio-domain
 * reading with no state-slice equivalent, same as the meter itself. */
function LimiterIndicator({
  limiter,
}: {
  limiter: RefObject<DynamicsCompressorNode | null>
}) {
  const [active, setActive] = useState(false)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    function tick() {
      setActive((limiter.current?.reduction ?? 0) < -0.1)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [limiter])

  return (
    <span
      data-testid="limiter-active-indicator"
      data-active={active}
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        active ? "text-destructive" : "text-muted-foreground"
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          active ? "bg-destructive" : "bg-muted"
        )}
      />
      Limiting
    </span>
  )
}

export function MasterBusPanel({
  analyserLeft,
  analyserRight,
  limiter,
}: {
  analyserLeft: RefObject<AnalyserNode | null>
  analyserRight: RefObject<AnalyserNode | null>
  limiter: RefObject<DynamicsCompressorNode | null>
}) {
  const { state, dispatch } = useStudio()
  const bus = state.masterBus

  return (
    <div className="flex flex-col gap-4">
      <StereoMeter analyserLeft={analyserLeft} analyserRight={analyserRight} />

      <LabeledSlider
        label="Master volume"
        value={bus.masterVolumeDb}
        min={MASTER_VOLUME_DB_MIN}
        max={MASTER_VOLUME_DB_MAX}
        step={1}
        format={formatVolumeDb}
        onValueChange={(v) =>
          dispatch({ type: "SET_MASTER_VOLUME", volumeDb: v })
        }
      />

      <div className="flex flex-col gap-2">
        <SectionHeading>EQ</SectionHeading>
        <LabeledSlider
          label="Low shelf frequency"
          value={bus.eq.lowShelf.freqHz}
          min={EQ_LOW_SHELF_FREQ_MIN}
          max={EQ_LOW_SHELF_FREQ_MAX}
          step={5}
          format={formatHz}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "low", freqHz: v })
          }
        />
        <LabeledSlider
          label="Low shelf gain"
          value={bus.eq.lowShelf.gainDb}
          min={EQ_GAIN_DB_MIN}
          max={EQ_GAIN_DB_MAX}
          step={1}
          format={formatDb}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "low", gainDb: v })
          }
        />
        <LabeledSlider
          label="Mid frequency"
          value={bus.eq.midPeak.freqHz}
          min={EQ_MID_FREQ_MIN}
          max={EQ_MID_FREQ_MAX}
          step={10}
          format={formatHz}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "mid", freqHz: v })
          }
        />
        <LabeledSlider
          label="Mid gain"
          value={bus.eq.midPeak.gainDb}
          min={EQ_GAIN_DB_MIN}
          max={EQ_GAIN_DB_MAX}
          step={1}
          format={formatDb}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "mid", gainDb: v })
          }
        />
        <LabeledSlider
          label="Mid Q"
          value={bus.eq.midPeak.q}
          min={EQ_Q_MIN}
          max={EQ_Q_MAX}
          step={0.1}
          format={formatQ}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "mid", q: v })
          }
        />
        <LabeledSlider
          label="High shelf frequency"
          value={bus.eq.highShelf.freqHz}
          min={EQ_HIGH_SHELF_FREQ_MIN}
          max={EQ_HIGH_SHELF_FREQ_MAX}
          step={50}
          format={formatHz}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "high", freqHz: v })
          }
        />
        <LabeledSlider
          label="High shelf gain"
          value={bus.eq.highShelf.gainDb}
          min={EQ_GAIN_DB_MIN}
          max={EQ_GAIN_DB_MAX}
          step={1}
          format={formatDb}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_EQ", band: "high", gainDb: v })
          }
        />
      </div>

      <div className="flex flex-col gap-2">
        <SectionHeading>Compressor</SectionHeading>
        <LabeledSlider
          label="Threshold"
          value={bus.compressor.thresholdDb}
          min={COMPRESSOR_THRESHOLD_DB_MIN}
          max={COMPRESSOR_THRESHOLD_DB_MAX}
          step={1}
          format={formatDb}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_COMPRESSOR", thresholdDb: v })
          }
        />
        <LabeledSlider
          label="Ratio"
          value={bus.compressor.ratio}
          min={COMPRESSOR_RATIO_MIN}
          max={COMPRESSOR_RATIO_MAX}
          step={1}
          format={formatRatio}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_COMPRESSOR", ratio: v })
          }
        />
        <LabeledSlider
          label="Attack"
          value={bus.compressor.attackSec}
          min={COMPRESSOR_ATTACK_SEC_MIN}
          max={COMPRESSOR_ATTACK_SEC_MAX}
          step={0.001}
          format={formatMs}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_COMPRESSOR", attackSec: v })
          }
        />
        <LabeledSlider
          label="Release"
          value={bus.compressor.releaseSec}
          min={COMPRESSOR_RELEASE_SEC_MIN}
          max={COMPRESSOR_RELEASE_SEC_MAX}
          step={0.01}
          format={formatMs}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_COMPRESSOR", releaseSec: v })
          }
        />
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <SectionHeading>Limiter</SectionHeading>
          <LimiterIndicator limiter={limiter} />
        </div>
        <LabeledSlider
          label="Ceiling"
          value={bus.limiterCeilingDb}
          min={LIMITER_CEILING_DB_MIN}
          max={LIMITER_CEILING_DB_MAX}
          step={0.1}
          format={formatDb}
          onValueChange={(v) =>
            dispatch({ type: "SET_MASTER_LIMITER_CEILING", ceilingDb: v })
          }
        />
      </div>
    </div>
  )
}
