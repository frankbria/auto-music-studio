"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { DiscoverSection } from "./DiscoverSection"

// Explore's Trending row (US-20.1, #656): plays + 3 x likes + 5 x shares inside the range. A plain two-Button group
// (no ToggleGroup primitive in the kit). Keyed on the range, so switching it reloads the row from a fresh state.

const RANGES = [
  { value: "trending_24h", label: "24h" },
  { value: "trending_7d", label: "7d" },
] as const

type TrendingSort = (typeof RANGES)[number]["value"]

export function TrendingSection() {
  const [sort, setSort] = useState<TrendingSort>("trending_24h")

  const toggle = (
    <div
      role="group"
      aria-label="Trending time range"
      data-slot="button-group"
      className="flex gap-1"
    >
      {RANGES.map((range) => (
        <Button
          key={range.value}
          size="sm"
          variant={sort === range.value ? "default" : "outline"}
          aria-pressed={sort === range.value}
          onClick={() => setSort(range.value)}
        >
          {range.label}
        </Button>
      ))}
    </div>
  )

  return (
    <DiscoverSection
      key={sort}
      title="Trending"
      sort={sort}
      action={toggle}
      emptyText="Nothing trending yet."
    />
  )
}
