"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"
import { PaginationControls } from "@/components/workspace/PaginationControls"
import { SortDropdown } from "@/components/workspace/SortDropdown"
import { useClips } from "@/hooks/use-clips"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { useWorkspaces } from "@/hooks/use-workspaces"
import { modeLabel } from "@/lib/clip-labels"
import { formatTime } from "@/lib/clips"
import type { SortOrder } from "@/lib/workspace-clips"

const PER_PAGE = 20

/**
 * Release song picker (US-21.1). Browse the workspace's clips and pick one to
 * master/distribute; the chosen clip id is handed back via `onSelect`. Reuses
 * the workspace library's data hooks and search/sort/pager controls so the
 * selection experience matches the Create page's clip library.
 *
 * ponytail: scoped to the default workspace (like WorkspacePanel, the app's own
 * clip library) — no workspace-switcher UI exists yet. Add a workspace dropdown
 * here if/when multi-workspace switching lands.
 */
export function SongSelector({
  onSelect,
  onCancel,
}: {
  onSelect: (clipId: string) => void
  /** Shown as a "Cancel" affordance only when a song is already selected. */
  onCancel?: () => void
}) {
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<SortOrder>("newest")
  const [page, setPage] = useState(1)
  const debouncedSearch = useDebouncedValue(search, 300)

  // New search/sort restarts paging from page 1 (in the handler, not an effect,
  // to avoid a cascading render — mirrors WorkspacePanel).
  const onSearchChange = (value: string) => {
    setSearch(value)
    setPage(1)
  }
  const onSortChange = (value: SortOrder) => {
    setSort(value)
    setPage(1)
  }

  const { defaultWorkspace, loading: workspacesLoading } = useWorkspaces()
  const {
    data,
    loading: clipsLoading,
    error,
  } = useClips(
    {
      workspace_id: defaultWorkspace?.id,
      search: debouncedSearch,
      sort,
      page,
      per_page: PER_PAGE,
    },
    // Defer until a workspace is resolved so we never fetch unscoped clips.
    { enabled: defaultWorkspace !== null }
  )

  const loading = workspacesLoading || clipsLoading
  const clips = data?.clips ?? []
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="flex flex-col gap-3">
      <ClipSearchInput value={search} onChange={onSearchChange} />
      <div className="flex items-center justify-between gap-2">
        <SortDropdown value={sort} onChange={onSortChange} />
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>

      {loading ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading clips…
        </p>
      ) : error ? (
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load clips. Please try again.
        </p>
      ) : clips.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {search ? "No clips match your search." : "No clips yet."}
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {clips.map((clip) => {
            const label = modeLabel(clip.generation_mode)
            return (
              <li key={clip.id}>
                <button
                  type="button"
                  onClick={() => onSelect(clip.id)}
                  className="flex w-full items-center gap-3 rounded-lg border border-border bg-card p-2 text-left transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <HugeiconsIcon icon={MusicNote01Icon} size={18} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">
                      {clip.title ?? "Untitled clip"}
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {formatTime(clip.duration ?? 0)}
                    </span>
                  </span>
                  {label && (
                    <Badge variant="outline" className="text-[10px]">
                      {label}
                    </Badge>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {!loading && !error && clips.length > 0 && (
        <PaginationControls
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      )}
    </div>
  )
}
