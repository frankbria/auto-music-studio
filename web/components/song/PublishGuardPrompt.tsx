"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { PublishGuard } from "@/hooks/use-song-actions"

// US-17.6: shown when a publish is blocked because the clip isn't presentable
// yet — it needs a title and at least one style tag before it can go public.
// Purely informational (the repo has no per-clip style-tag editor surface in
// this story); it names exactly what's missing and dismisses. `guard` is null
// when there's nothing to show.

export type PublishGuardPromptProps = {
  guard: PublishGuard | null
  onClose: () => void
}

export function PublishGuardPrompt({ guard, onClose }: PublishGuardPromptProps) {
  const missing: string[] = []
  if (guard?.missingTitle) missing.push("a title")
  if (guard?.missingStyleTags) missing.push("at least one style tag")

  return (
    <Dialog open={guard !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HugeiconsIcon icon={Alert01Icon} size={20} />
            Add details before publishing
          </DialogTitle>
          <DialogDescription>
            Publishing makes this song public. Add {missing.join(" and ")} first,
            then try again.
          </DialogDescription>
        </DialogHeader>
        {missing.length > 0 && (
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            {missing.map((item) => (
              <li key={item}>Missing {item}</li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button onClick={onClose}>Got it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
