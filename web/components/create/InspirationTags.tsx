"use client"

import { useMemo, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Cancel01Icon, ShuffleIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { STYLE_SUGGESTIONS } from "@/lib/profile"

// Curated pool the suggestions are drawn from. Reuses the profile style list
// (genres, moods, instruments) so there's one source of style vocabulary; an
// API-driven source can replace this later without touching the component API.
const TAG_POOL = STYLE_SUGGESTIONS
const SUGGESTION_COUNT = 8

/** Pick `count` distinct tags at random from `pool`, excluding `exclude`. */
function pickSuggestions(
  pool: readonly string[],
  count: number,
  exclude: string[]
): string[] {
  const taken = new Set(exclude)
  const candidates = pool.filter((t) => !taken.has(t))
  // Fisher–Yates over a copy, then slice — unbiased and short.
  for (let i = candidates.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[candidates[i], candidates[j]] = [candidates[j], candidates[i]]
  }
  return candidates.slice(0, count)
}

/**
 * AI-suggested inspiration tags: a row of clickable style pills plus a shuffle
 * button. Selected tags are owned by the parent (they feed the `style` field of
 * the generation request); shuffling refreshes the unselected suggestions while
 * keeping the current selection visible as removable chips.
 */
export function InspirationTags({
  selectedTags,
  onChange,
}: {
  selectedTags: string[]
  onChange: (next: string[]) => void
}) {
  const [suggestions, setSuggestions] = useState<string[]>(() =>
    pickSuggestions(TAG_POOL, SUGGESTION_COUNT, [])
  )

  // Show suggestions that aren't already selected, so a selected pill doesn't
  // appear in both rows at once.
  const visibleSuggestions = useMemo(
    () => suggestions.filter((t) => !selectedTags.includes(t)),
    [suggestions, selectedTags]
  )

  function toggle(tag: string) {
    onChange(
      selectedTags.includes(tag)
        ? selectedTags.filter((t) => t !== tag)
        : [...selectedTags, tag]
    )
  }

  function shuffle() {
    setSuggestions(pickSuggestions(TAG_POOL, SUGGESTION_COUNT, selectedTags))
  }

  return (
    <div className="flex flex-col gap-3">
      {selectedTags.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Selected tags">
          {selectedTags.map((tag) => (
            <Badge key={tag} variant="default" className="gap-1 pr-1">
              {tag}
              <button
                type="button"
                aria-label={`Remove ${tag}`}
                onClick={() => toggle(tag)}
                className="rounded-full p-0.5 hover:bg-primary-foreground/20"
              >
                <HugeiconsIcon icon={Cancel01Icon} className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {visibleSuggestions.map((tag) => (
          <Badge key={tag} variant="outline" asChild>
            <button type="button" onClick={() => toggle(tag)}>
              {tag}
            </button>
          </Badge>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Shuffle suggestions"
          onClick={shuffle}
        >
          <HugeiconsIcon icon={ShuffleIcon} />
        </Button>
      </div>
    </div>
  )
}
