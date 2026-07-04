"use client"

import type { ReactNode } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import type { ClipEditState } from "@/hooks/use-clip-edit"

// Shared frame for every editing workflow modal (US-17.3). Owns the phase-driven
// chrome — the form (idle), an in-flight spinner (submitting/polling), a success
// state that links to the resulting clip, and an inline error with Retry — so
// each modal only supplies its own fields and submit closure. On success it can
// navigate to the new clip so "results appear as new clips" is reachable from
// the song page, which has no workspace panel of its own.

export function EditModalShell({
  open,
  onOpenChange,
  title,
  description,
  state,
  onSubmit,
  canSubmit,
  submitLabel = "Create",
  creditHint,
  onRetry,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  state: ClipEditState
  onSubmit: () => void
  canSubmit: boolean
  submitLabel?: string
  creditHint?: string
  onRetry: () => void
  children: ReactNode
}) {
  const router = useRouter()
  const busy = state.phase === "submitting" || state.phase === "polling"

  function viewResult(clipId: string) {
    onOpenChange(false)
    router.push(`/song/${encodeURIComponent(clipId)}`)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        {state.phase === "success" ? (
          <div role="status" className="flex flex-col gap-3 text-sm">
            <p>
              {state.clipIds.length > 1
                ? `${state.clipIds.length} new clips are ready.`
                : "Your new clip is ready."}
            </p>
          </div>
        ) : busy ? (
          <div role="status" className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <HugeiconsIcon icon={Loading03Icon} className="animate-spin" data-icon="inline-start" />
            <span>
              Working…
              {state.phase === "polling" && state.estimatedSeconds > 0
                ? ` ~${state.estimatedSeconds}s`
                : ""}
            </span>
            {state.phase === "polling" && state.progress && (
              <span className="text-xs">{state.progress}</span>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-4">{children}</div>
        )}

        {state.phase === "error" && (
          <p role="alert" className="text-sm text-destructive">
            {state.message}
          </p>
        )}

        <DialogFooter>
          {state.phase === "success" ? (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button onClick={() => viewResult(state.clipIds[0])} disabled={state.clipIds.length === 0}>
                View
              </Button>
            </>
          ) : state.phase === "error" ? (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={onRetry}>Try again</Button>
            </>
          ) : (
            <>
              {creditHint && !busy && (
                <span className="mr-auto self-center text-xs text-muted-foreground">
                  {creditHint}
                </span>
              )}
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={onSubmit} disabled={!canSubmit || busy}>
                {busy ? "Working…" : submitLabel}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
