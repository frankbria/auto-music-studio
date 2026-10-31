"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  Loading03Icon,
  SearchRemoveIcon,
} from "@hugeicons/core-free-icons"

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
import { fetchFacets, type DiscoverFacets } from "@/lib/discover"
import { GENRES } from "@/lib/explore"
import {
  buildSearchQuery,
  parseSearchParams,
  searchClips,
  SEARCH_SORTS,
  type SearchParams,
} from "@/lib/search"
import type { Clip } from "@/lib/workspace-clips"
import { SearchFilters } from "./SearchFilters"

// Prop-driven Search page UI (US-20.2). All search state lives in `params`; every
// change flows out through `onChange` (the SearchPageClient wrapper writes it to
// the URL). The debounced search box pushes its value outward on a timer, so
// there is no URL<->state loop. Results come from the discovery API (#651): they
// are tagged with the search they answer, so "loading" is derived (the tag isn't
// the current search) and state is only set when a fetch settles.

type Results = {
  /** buildSearchQuery() of the search these results answer. */
  forKey: string
  failed: boolean
  clips: Clip[]
  nextCursor: string | null
  total: number
  loadingMore: boolean
  loadMoreFailed: boolean
}

const settled = (
  forKey: string,
  failed: boolean,
  page?: Pick<Results, "clips" | "nextCursor" | "total">
): Results => ({
  forKey,
  failed,
  clips: page?.clips ?? [],
  nextCursor: page?.nextCursor ?? null,
  total: page?.total ?? 0,
  loadingMore: false,
  loadMoreFailed: false,
})

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
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    []
  )

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

  const searchKey = buildSearchQuery(params)
  const [results, setResults] = useState<Results | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [facets, setFacets] = useState<DiscoverFacets>({ keys: [], models: [] })

  useEffect(() => {
    // Facets only fill the key/model dropdowns; without them both stay at "Any".
    fetchFacets().then(setFacets, () => {})
  }, [])

  useEffect(() => {
    if (showSuggestions) return
    let current = true
    // Rebuilt from the key so the effect keys on the search, not on params' identity.
    searchClips(parseSearchParams(new URLSearchParams(searchKey))).then(
      (page) => {
        if (current) setResults(settled(searchKey, false, page))
      },
      () => {
        if (current) setResults(settled(searchKey, true))
      }
    )
    return () => {
      current = false
    }
  }, [searchKey, showSuggestions, attempt])

  const shown = results?.forKey === searchKey ? results : null

  const retry = () => {
    setResults(null)
    setAttempt((n) => n + 1)
  }

  const loadMore = (page: Results) => {
    if (page.loadingMore || !page.nextCursor) return
    setResults({ ...page, loadingMore: true, loadMoreFailed: false })
    const sameSearch = (latest: Results | null): latest is Results =>
      latest?.forKey === page.forKey
    searchClips(params, page.nextCursor).then(
      (next) =>
        setResults((latest) =>
          sameSearch(latest)
            ? {
                ...latest,
                clips: [...latest.clips, ...next.clips],
                nextCursor: next.nextCursor,
                total: next.total,
                loadingMore: false,
              }
            : latest
        ),
      () =>
        setResults((latest) =>
          sameSearch(latest)
            ? { ...latest, loadingMore: false, loadMoreFailed: true }
            : latest
        )
    )
  }

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
        <SortDropdown
          value={params.sort}
          onChange={(sort) => onChange({ sort })}
        />
      </div>

      <div className="flex flex-col gap-8 lg:flex-row">
        <aside className="lg:w-56 lg:shrink-0">
          <SearchFilters
            params={params}
            onChange={onChange}
            keys={facets.keys}
            models={facets.models}
          />
        </aside>

        <div className="flex-1">
          {showSuggestions ? (
            <EmptyState
              onPick={commitQuery}
              onGenre={(style) => onChange({ style })}
            />
          ) : !shown ? (
            <Searching />
          ) : shown.failed ? (
            <SearchError onRetry={retry} />
          ) : shown.total === 0 ? (
            <NoResults />
          ) : (
            <div className="flex flex-col gap-6">
              <p className="text-sm text-muted-foreground" aria-live="polite">
                {shown.total} {shown.total === 1 ? "result" : "results"}
              </p>
              <div className="flex flex-wrap gap-4">
                {shown.clips.map((clip) => (
                  <ExploreClipCard key={clip.id} clip={clip} />
                ))}
              </div>
              {shown.loadMoreFailed && (
                <p role="alert" className="text-sm text-destructive">
                  Couldn&apos;t load more results.
                </p>
              )}
              {shown.nextCursor && (
                <Button
                  variant="outline"
                  className="self-center"
                  disabled={shown.loadingMore}
                  onClick={() => loadMore(shown)}
                >
                  {shown.loadingMore ? "Loading…" : "Load more"}
                </Button>
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
        <span className="text-xs font-medium text-muted-foreground">
          Try searching
        </span>
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
        <span className="text-xs font-medium text-muted-foreground">
          Popular genres
        </span>
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

function Searching() {
  return (
    <div
      className="flex items-center justify-center gap-2 py-16 text-muted-foreground"
      data-testid="search-loading"
    >
      <HugeiconsIcon icon={Loading03Icon} size={20} className="animate-spin" />
      Searching…
    </div>
  )
}

function SearchError({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 py-16 text-center"
    >
      <p className="font-medium">Search is unavailable right now.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
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
