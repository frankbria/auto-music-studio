"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Cancel01Icon,
  CheckmarkCircle01Icon,
  Download04Icon,
  LinkSquare02Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  prepareDistribution,
  targetById,
  type GuidedTarget,
  type PreparedPackage,
} from "@/lib/distribution"
import type { ReleaseMetadata } from "@/lib/release-draft"
import { useNotify } from "@/contexts/notifications-context"

type Props = {
  target: GuidedTarget
  /** Whether a song is selected; false disables the flow. */
  ready: boolean
  /**
   * Resolve the release metadata to package, read fresh when the modal opens so
   * the package reflects the latest saved draft rather than a mount-time snapshot.
   * Returns null when no song is selected.
   */
  resolveMetadata: () => ReleaseMetadata | null
}

/** Guided LANDR/DistroKid flow (US-21.5): prepare a package, then upload it manually. */
export function GuidedFlowModal({ target, ready, resolveMetadata }: Props) {
  const notify = useNotify()
  const info = targetById(target)!
  const [open, setOpen] = useState(false)
  const [pkg, setPkg] = useState<PreparedPackage | null>(null)
  const [submitted, setSubmitted] = useState(false)
  // Track the live bundle object URL so it's revoked on close AND on unmount
  // (Radix only fires onOpenChange for an actual close, not an unmount).
  const bundleUrl = useRef<string | null>(null)

  function revokeBundle() {
    if (bundleUrl.current) {
      URL.revokeObjectURL(bundleUrl.current)
      bundleUrl.current = null
    }
  }

  useEffect(() => revokeBundle, [])

  function handleOpenChange(next: boolean) {
    if (next) {
      const metadata = resolveMetadata()
      if (!metadata) return
      // Compute the package in the open transition (not an effect) so the bundle
      // object URL is created once per open. Revoke any prior one first.
      revokeBundle()
      const prepared = prepareDistribution(target, metadata)
      bundleUrl.current = prepared.bundleUrl
      setPkg(prepared)
      setSubmitted(false)
    } else {
      revokeBundle()
      setPkg(null)
    }
    setOpen(next)
  }

  function markSubmitted() {
    setSubmitted(true)
    // Seam: no real release_id yet, so record the submission locally + notify.
    // Swaps to POST /releases/{id}/submit/{target} when release-creation lands.
    notify({
      type: "distribution_update",
      message: `${info.label} submission marked as sent.`,
      href: "/release?tab=distribute",
    })
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={!ready}
        onClick={() => handleOpenChange(true)}
      >
        Prepare package
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Prepare for {info.label}</DialogTitle>
            <DialogDescription>
              {pkg?.allChecksPassed
                ? "Your release is ready. Download the package and upload it on " +
                  info.label +
                  "."
                : "Resolve the items below on the metadata tab, then reopen this to prepare."}
            </DialogDescription>
          </DialogHeader>

          {pkg && (
            <div className="flex flex-col gap-4">
              <ul className="flex flex-col gap-2">
                {pkg.checklist.map((c) => (
                  <li key={c.item} className="flex items-start gap-2 text-sm">
                    <HugeiconsIcon
                      icon={c.passed ? CheckmarkCircle01Icon : Cancel01Icon}
                      size={16}
                      className={
                        c.passed
                          ? "mt-0.5 shrink-0 text-emerald-500"
                          : "mt-0.5 shrink-0 text-destructive"
                      }
                    />
                    <span>
                      <span className="font-medium">{c.item}</span>
                      <span className="block text-xs text-muted-foreground">{c.message}</span>
                    </span>
                  </li>
                ))}
              </ul>

              {pkg.allChecksPassed && (
                <>
                  <pre className="max-h-40 overflow-auto rounded-md bg-muted/50 p-3 text-xs whitespace-pre-wrap text-muted-foreground">
                    {pkg.instructions}
                  </pre>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button asChild variant="outline" size="sm">
                      <a href={pkg.bundleUrl!} download={`${target}-release-package.json`}>
                        <HugeiconsIcon icon={Download04Icon} size={16} />
                        Download package
                      </a>
                    </Button>
                    {info.portalUrl && (
                      <Button asChild size="sm">
                        <a href={info.portalUrl} target="_blank" rel="noopener noreferrer">
                          <HugeiconsIcon icon={LinkSquare02Icon} size={16} />
                          Open {info.label}
                        </a>
                      </Button>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="self-start"
                    disabled={submitted}
                    onClick={markSubmitted}
                  >
                    {submitted ? (
                      <>
                        <HugeiconsIcon
                          icon={CheckmarkCircle01Icon}
                          size={16}
                          className="text-emerald-500"
                        />
                        Marked as submitted
                      </>
                    ) : (
                      "Mark as submitted"
                    )}
                  </Button>
                </>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
