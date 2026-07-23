"use client"

import type { MasteringMetrics } from "@/lib/mastering"

/** Signed dB string, e.g. "+6.0 dB" / "-2.3 dB". */
function signed(value: number, unit = " dB") {
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}${unit}`
}

/**
 * A centered EQ bar chart (US-21.2). Each band's gain is drawn as a bar above or
 * below a zero line, normalized to the largest magnitude present. Dolby returns
 * 16 bands; other services may return none (then this isn't rendered).
 */
function EqBands({ bands }: { bands: number[] }) {
  const peak = Math.max(1e-6, ...bands.map((b) => Math.abs(b)))
  const width = 200
  const height = 60
  const mid = height / 2
  const barW = width / bands.length
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-16 w-full max-w-xs"
      role="img"
      aria-label={`Equalizer, ${bands.length} bands`}
    >
      <line x1={0} y1={mid} x2={width} y2={mid} className="stroke-border" strokeWidth={1} />
      {bands.map((gain, i) => {
        const h = (Math.abs(gain) / peak) * (mid - 2)
        const x = i * barW + barW * 0.15
        const y = gain >= 0 ? mid - h : mid
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW * 0.7}
            height={h}
            className="fill-primary"
          />
        )
      })}
    </svg>
  )
}

/**
 * Mastering analysis metrics for the selected preview (US-21.2): integrated
 * loudness (with delta vs. original), a 16-band EQ visualization, and stereo
 * image — each shown only when the backend provides it, so a loudness-only
 * service (Bakuage) degrades gracefully to just the loudness row.
 */
export function MasteringMetrics({
  metrics,
  loudnessDelta,
}: {
  metrics?: MasteringMetrics
  loudnessDelta?: number | null
}) {
  const hasLoudness = metrics?.loudness !== undefined
  const hasEq = !!metrics?.eq_bands && metrics.eq_bands.length > 0
  const hasStereo =
    metrics?.stereo_width !== undefined || metrics?.stereo_balance !== undefined

  if (!metrics || (!hasLoudness && !hasEq && !hasStereo)) {
    return <p className="text-sm text-muted-foreground">Metrics not available.</p>
  }

  return (
    <dl className="flex flex-col gap-3 text-sm">
      {hasLoudness && (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="text-muted-foreground">Loudness</dt>
          <dd className="tabular-nums">
            {metrics.loudness!.toFixed(1)} LUFS
            {loudnessDelta !== null && loudnessDelta !== undefined && (
              <span className="ml-1 text-muted-foreground">
                ({signed(loudnessDelta)} vs. original)
              </span>
            )}
          </dd>
        </div>
      )}

      {hasEq && (
        <div className="flex flex-col gap-1">
          <dt className="text-muted-foreground">EQ</dt>
          <dd>
            <EqBands bands={metrics.eq_bands!} />
          </dd>
        </div>
      )}

      {hasStereo && (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="text-muted-foreground">Stereo image</dt>
          <dd className="tabular-nums">
            {metrics.stereo_width !== undefined && (
              <span>width {metrics.stereo_width.toFixed(2)}</span>
            )}
            {metrics.stereo_balance !== undefined && (
              <span className="ml-2">balance {signed(metrics.stereo_balance, "")}</span>
            )}
          </dd>
        </div>
      )}
    </dl>
  )
}
