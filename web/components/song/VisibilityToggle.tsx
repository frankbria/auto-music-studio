"use client"

import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react"
import { GlobeIcon, LinkIcon, LockIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import type { Visibility } from "@/lib/workspace-clips"

// US-20.7: Private/Unlisted/Public picker, replacing the two-state publish
// toggle (US-17.6). Built on the same dropdown-menu radio primitive as
// SortDropdown — the auto check indicator marks the current selection.

const ORDER: Visibility[] = ["private", "unlisted", "public"]

const CONFIG: Record<Visibility, { label: string; icon: IconSvgElement }> = {
  private: { label: "Private", icon: LockIcon },
  unlisted: { label: "Unlisted", icon: LinkIcon },
  public: { label: "Public", icon: GlobeIcon },
}

export type VisibilityToggleProps = {
  value: Visibility
  onChange: (next: Visibility) => void
  disabled?: boolean
}

export function VisibilityToggle({
  value,
  onChange,
  disabled = false,
}: VisibilityToggleProps) {
  const current = CONFIG[value]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Visibility: ${current.label}`}
          disabled={disabled}
          className={cn(value === "public" && "text-primary")}
        >
          <HugeiconsIcon icon={current.icon} size={16} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(v) => onChange(v as Visibility)}
        >
          {ORDER.map((v) => (
            <DropdownMenuRadioItem key={v} value={v}>
              <HugeiconsIcon icon={CONFIG[v].icon} size={14} />
              {CONFIG[v].label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
