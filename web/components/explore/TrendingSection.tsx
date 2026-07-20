"use client"

import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { getTrendingClips, type TrendingRange } from "@/lib/explore"
import { ExploreClipCard } from "./ExploreClipCard"
import { SectionRow } from "./SectionRow"

// Trending section (US-20.1, AC2). A 24h/7d segmented toggle re-reads the mock
// service; the two ranges rank by different signals, so the row reorders. Uses a
// plain two-Button group (no ToggleGroup primitive in the kit, and Tabs would
// unmount the row on switch).

const RANGES: { value: TrendingRange; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
]

export function TrendingSection() {
  const [range, setRange] = useState<TrendingRange>("24h")
  const clips = useMemo(() => getTrendingClips(range), [range])

  const toggle = (
    <div
      role="group"
      aria-label="Trending time range"
      data-slot="button-group"
      className="flex gap-1"
    >
      {RANGES.map((r) => (
        <Button
          key={r.value}
          size="sm"
          variant={range === r.value ? "default" : "outline"}
          aria-pressed={range === r.value}
          onClick={() => setRange(r.value)}
        >
          {r.label}
        </Button>
      ))}
    </div>
  )

  return (
    <SectionRow title="Trending" action={toggle}>
      {clips.map((clip) => (
        <ExploreClipCard key={clip.id} clip={clip} />
      ))}
    </SectionRow>
  )
}
