"use client"

import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import { StarIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { PRO_BENEFITS, UPGRADE_URL, type LockedFeature } from "@/lib/tiers"

/**
 * What a free-tier musician sees when they reach for a Pro feature (US-26.2 AC2).
 *
 * The story is specific that this is an **upgrade prompt, not an error** — and the
 * behaviour it replaces was neither: locked menu items were rendered `disabled`, so
 * clicking one did nothing at all. Silence is the worst of the three, because it reads
 * as a bug rather than as a boundary.
 *
 * Leads with the feature they actually asked for, so the prompt answers "why can't I do
 * this" before it sells anything.
 */
export function UpgradeModal({
  feature,
  open,
  onOpenChange,
}: {
  /** The feature that was reached for, or null when opened without one. */
  feature: LockedFeature | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="upgrade-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HugeiconsIcon icon={StarIcon} size={18} />
            {feature ? `${feature.name} is a Pro feature` : "Upgrade to Pro"}
          </DialogTitle>
          <DialogDescription>
            {feature
              ? `Upgrade to ${feature.benefit}.`
              : "Unlock everything Auto Music Studio can do."}
          </DialogDescription>
        </DialogHeader>

        <ul className="flex flex-col gap-2 text-sm">
          {PRO_BENEFITS.map((benefit) => (
            <li key={benefit} className="flex items-start gap-2">
              <span aria-hidden className="text-muted-foreground">
                •
              </span>
              <span>{benefit}</span>
            </li>
          ))}
        </ul>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Not now
          </Button>
          <Button asChild>
            <Link href={UPGRADE_URL}>See plans</Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
