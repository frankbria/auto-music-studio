"use client"

import { useEffect, useMemo, useState } from "react"

import { ClipList } from "@/components/workspace/ClipList"
import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"
import { FiltersButton } from "@/components/workspace/FiltersButton"
import { PaginationControls } from "@/components/workspace/PaginationControls"
import { SortDropdown } from "@/components/workspace/SortDropdown"
import { WorkspaceBreadcrumb } from "@/components/workspace/WorkspaceBreadcrumb"
import { usePlayer } from "@/contexts/player-context"
import { useClips } from "@/hooks/use-clips"
import { useWorkspaces } from "@/hooks/use-workspaces"
import {
  activeFilterCount,
  applyClientFilters,
  EMPTY_FILTERS,
  type ClipFilters,
  type SortOrder,
} from "@/lib/workspace-clips"

const PER_PAGE = 20

/** Debounce a rapidly-changing value (search keystrokes). */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

/**
 * Right-side clip library for the Create page (US-16.5). Owns search/filter/
 * sort/page state; search and sort drive the server query (via useClips) while
 * the Liked/Public/Uploads filters are applied client-side over the fetched page
 * (the backend has no params for them — see applyClientFilters). Has its own
 * scroll container so it scrolls independently of the creation form.
 */
export function WorkspacePanel({
  onNavigateWorkspaces,
}: {
  onNavigateWorkspaces?: () => void
}) {
  const [search, setSearch] = useState("")
  const [filters, setFilters] = useState<ClipFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<SortOrder>("newest")
  const [page, setPage] = useState(1)

  const debouncedSearch = useDebouncedValue(search, 300)

  // A new search term or sort order restarts paging from the first page (reset
  // in the handlers rather than an effect to avoid a cascading render).
  const onSearchChange = (value: string) => {
    setSearch(value)
    setPage(1)
  }
  const onSortChange = (value: SortOrder) => {
    setSort(value)
    setPage(1)
  }

  const { defaultWorkspace, loading: workspacesLoading } = useWorkspaces()
  const { data, loading: clipsLoading } = useClips({
    workspace_id: defaultWorkspace?.id,
    search: debouncedSearch,
    sort,
    page,
    per_page: PER_PAGE,
  })

  const { state } = usePlayer()
  const visibleClips = useMemo(
    () => applyClientFilters(data?.clips ?? [], filters, state.likedIds),
    [data, filters, state.likedIds]
  )

  const loading = workspacesLoading || clipsLoading
  const totalPages = data?.total_pages ?? 1
  const narrowed = activeFilterCount(filters) > 0 || debouncedSearch.length > 0

  return (
    <div data-testid="workspace-panel" className="flex h-full flex-col gap-3">
      <WorkspaceBreadcrumb
        workspace={defaultWorkspace}
        onNavigate={onNavigateWorkspaces}
      />
      <ClipSearchInput value={search} onChange={onSearchChange} />
      <div className="flex items-center justify-between gap-2">
        <FiltersButton filters={filters} onFiltersChange={setFilters} />
        <SortDropdown value={sort} onChange={onSortChange} />
      </div>

      <div className="-mr-1 flex-1 overflow-y-auto pr-1">
        <ClipList
          clips={visibleClips}
          loading={loading}
          emptyMessage={
            // Filters run client-side over the fetched page (the backend has no
            // params for them yet), so scope the wording to this page rather
            // than implying the whole library is empty.
            narrowed ? "No clips on this page match your filters." : "No clips yet."
          }
        />
      </div>

      <PaginationControls page={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  )
}
