"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { SortOrder } from "@/lib/workspace-clips"

const LABELS: Record<SortOrder, string> = {
  newest: "Newest",
  oldest: "Oldest",
}

/** Newest/Oldest sort selector. Built on the dropdown-menu radio primitive. */
export function SortDropdown({
  value,
  onChange,
}: {
  value: SortOrder
  onChange: (value: SortOrder) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1">
          {LABELS[value]}
          <HugeiconsIcon icon={ArrowDown01Icon} size={14} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(v) => onChange(v as SortOrder)}
        >
          <DropdownMenuRadioItem value="newest">Newest</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="oldest">Oldest</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
