"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { FilterIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Switch } from "@/components/ui/switch"
import { activeFilterCount, type ClipFilters } from "@/lib/workspace-clips"

const TOGGLES: { key: keyof ClipFilters; label: string }[] = [
  { key: "liked", label: "Liked" },
  { key: "public", label: "Public" },
  { key: "uploads", label: "Uploads" },
]

/**
 * Filters button + popover with Liked/Public/Uploads switches. The badge shows
 * the active-filter count. Filtering is applied client-side by the panel — see
 * applyClientFilters; the backend has no params for these yet.
 */
export function FiltersButton({
  filters,
  onFiltersChange,
}: {
  filters: ClipFilters
  onFiltersChange: (filters: ClipFilters) => void
}) {
  const count = activeFilterCount(filters)

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <HugeiconsIcon icon={FilterIcon} size={14} />
          Filters
          {count > 0 && (
            <Badge variant="secondary" className="ml-0.5 px-1.5">
              {count}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56">
        <div className="flex flex-col gap-3">
          {TOGGLES.map(({ key, label }) => (
            <div key={key} className="flex items-center justify-between gap-4">
              <Label htmlFor={`filter-${key}`}>{label}</Label>
              <Switch
                id={`filter-${key}`}
                checked={filters[key]}
                onCheckedChange={(checked) =>
                  onFiltersChange({ ...filters, [key]: checked })
                }
              />
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
