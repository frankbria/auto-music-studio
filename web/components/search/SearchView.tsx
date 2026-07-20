"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, SearchRemoveIcon } from "@hugeicons/core-free-icons"

import { ExploreClipCard } from "@/components/explore/ExploreClipCard"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"
import { PaginationControls } from "@/components/workspace/PaginationControls"
import { GENRES } from "@/lib/explore"
import {
  availableKeys,
  availableModels,
  paginate,
  searchClips,
  SEARCH_SORTS,
  type SearchParams,
} from "@/lib/search"
import { SearchFilters } from "./SearchFilters"

// Prop-driven Search page UI (US-20.2). All search state lives in `params`; every
// change flows out through `onChange` (the SearchPageClient wrapper writes it to
// the URL). The only local state is the debounced search box, which pushes its
// value outward on a timer — no effect, so no set-state-in-effect and no
// URL↔state loop. Results come from the synchronous mock seam (lib/search), so
// there is no loading or error state to render.

/** Example searches shown on the empty (no query, no filters) state. */
const SUGGESTIONS = ["chill beats", "upbeat pop", "lofi", "synthwave"]

function SortDropdown({
  value,
  onChange,
}: {
  value: SearchParams["sort"]
  onChange: (value: SearchParams["sort"]) => void
}) {
  const label = SEARCH_SORTS.find((s) => s.value === value)?.label ?? "Sort"
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="gap-1"
          aria-label={`Sort by: ${label}`}
        >
          {label}
          <HugeiconsIcon icon={ArrowDown01Icon} size={14} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(v) => onChange(v as SearchParams["sort"])}
        >
          {SEARCH_SORTS.map((s) => (
            <DropdownMenuRadioItem key={s.value} value={s.value}>
              {s.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function SearchView({
  params,
  onChange,
}: {
  params: SearchParams
  onChange: (patch: Partial<SearchParams>) => void
}) {
  // Local display value for the search box; the committed (debounced) value is
  // `params.q`. Initialized once — the box is the input's source of truth.
  const [text, setText] = useState(params.q)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const commitQuery = (value: string, delayMs: number) => {
    setText(value)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange({ q: value }), delayMs)
  }

  // Cancel a pending commit if the page unmounts mid-debounce (avoids a
  // router.replace against an unmounted component).
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const results = searchClips(params)
  const page = paginate(results, params.page)

  const hasFilter =
    !!params.style ||
    params.bpmMin != null ||
    params.bpmMax != null ||
    !!params.key ||
    !!params.model
  // AC5: an empty query with no active filter is the "browse" landing — show
  // suggestions rather than the full pool. A genre deep link (/search?style=…)
  // sets a filter, so it skips this and shows results.
  const showSuggestions = !params.q.trim() && !hasFilter

  return (
    <div className="flex flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Search</h1>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <ClipSearchInput
          value={text}
          onChange={(v) => commitQuery(v, v ? 300 : 0)}
          placeholder="Search songs, styles, lyrics…"
          ariaLabel="Search songs"
          className="flex-1"
        />
        <SortDropdown value={params.sort} onChange={(sort) => onChange({ sort })} />
      </div>

      <div className="flex flex-col gap-8 lg:flex-row">
        <aside className="lg:w-56 lg:shrink-0">
          <SearchFilters
            params={params}
            onChange={onChange}
            keys={availableKeys()}
            models={availableModels()}
          />
        </aside>

        <div className="flex-1">
          {showSuggestions ? (
            <EmptyState onPick={commitQuery} onGenre={(style) => onChange({ style })} />
          ) : page.total === 0 ? (
            <NoResults />
          ) : (
            <div className="flex flex-col gap-6">
              <p className="text-sm text-muted-foreground" aria-live="polite">
                {page.total} {page.total === 1 ? "result" : "results"}
              </p>
              <div className="flex flex-wrap gap-4">
                {page.clips.map((clip) => (
                  <ExploreClipCard key={clip.id} clip={clip} />
                ))}
              </div>
              {page.totalPages > 1 && (
                <PaginationControls
                  page={page.page}
                  totalPages={page.totalPages}
                  onPageChange={(p) => onChange({ page: p })}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EmptyState({
  onPick,
  onGenre,
}: {
  onPick: (value: string, delayMs: number) => void
  onGenre: (slug: string) => void
}) {
  return (
    <div className="flex flex-col gap-6 py-8" data-testid="search-empty">
      <p className="text-muted-foreground">
        Search for a song, style, or lyric — or start from a suggestion.
      </p>
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">Try searching</span>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((term) => (
            <button
              key={term}
              type="button"
              onClick={() => onPick(term, 0)}
              className="rounded-full border border-border px-3 py-1 text-sm transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {term}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">Popular genres</span>
        <div className="flex flex-wrap gap-2">
          {GENRES.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => onGenre(g.slug)}
              className="rounded-full border border-border px-3 py-1 text-sm transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {g.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function NoResults() {
  return (
    <div
      className="flex flex-col items-center gap-3 py-16 text-center"
      data-testid="search-no-results"
    >
      <HugeiconsIcon
        icon={SearchRemoveIcon}
        size={32}
        aria-hidden
        className="text-muted-foreground"
      />
      <p className="font-medium">No songs found</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        Try a different search term, widen the BPM range, or clear some filters.
      </p>
    </div>
  )
}
