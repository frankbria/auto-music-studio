"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowLeft01Icon, ArrowRight01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

/** Previous/Next pager with a "Page X of Y" indicator. */
export function PaginationControls({
  page,
  totalPages,
  onPageChange,
}: {
  page: number
  totalPages: number
  onPageChange: (page: number) => void
}) {
  // Clamp once so an empty result (total_pages: 0) shows "Page 1 of 1" *and*
  // disables Next, rather than leaving Next clickable into an empty page 2.
  const clampedTotalPages = Math.max(totalPages, 1)
  return (
    <div className="flex items-center justify-between gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Previous page"
      >
        <HugeiconsIcon icon={ArrowLeft01Icon} size={14} />
        Prev
      </Button>
      <span className="text-sm text-muted-foreground" aria-live="polite">
        Page {page} of {clampedTotalPages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= clampedTotalPages}
        onClick={() => onPageChange(page + 1)}
        aria-label="Next page"
      >
        Next
        <HugeiconsIcon icon={ArrowRight01Icon} size={14} />
      </Button>
    </div>
  )
}
