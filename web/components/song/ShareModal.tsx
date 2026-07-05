"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  CheckmarkCircle01Icon,
  Copy01Icon,
  Facebook01Icon,
  NewTwitterIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

// US-17.6: the Share modal for a clip. Client-only — the share URL is built
// from the clip id (Design Choice 2: no share_slug), so there's no backend
// call. Copy-to-clipboard gives inline "Copied!" feedback (the repo has no
// toast primitive); X/Facebook open their share-intent pages in a new tab.

export type ShareModalProps = {
  open: boolean
  clipId: string
  clipTitle: string | null
  onClose: () => void
}

/** Public share URL for a clip: `{origin}/song/{clipId}`. */
export function shareUrlForClip(clipId: string): string {
  const origin =
    typeof window !== "undefined" ? window.location.origin : ""
  return `${origin}/song/${encodeURIComponent(clipId)}`
}

export function ShareModal({ open, clipId, clipTitle, onClose }: ShareModalProps) {
  const [copied, setCopied] = useState(false)
  const url = shareUrlForClip(clipId)
  const title = clipTitle ?? "Untitled clip"

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      // Revert the label so a second copy still reads as an action.
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked (permissions / insecure context) — the read-only
      // field is still selectable, so the user can copy manually.
      setCopied(false)
    }
  }

  const shareIntents = [
    {
      label: "Share on X",
      icon: NewTwitterIcon,
      href: `https://twitter.com/intent/tweet?url=${encodeURIComponent(
        url
      )}&text=${encodeURIComponent(title)}`,
    },
    {
      label: "Share on Facebook",
      icon: Facebook01Icon,
      href: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(
        url
      )}`,
    },
  ]

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share &ldquo;{title}&rdquo;</DialogTitle>
          <DialogDescription>
            Anyone with the link can open this song.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Input
            aria-label="Share link"
            readOnly
            value={url}
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button
            type="button"
            variant={copied ? "outline" : "default"}
            onClick={copyLink}
            aria-label="Copy link"
          >
            <HugeiconsIcon
              icon={copied ? CheckmarkCircle01Icon : Copy01Icon}
              size={16}
            />
            {copied ? "Copied!" : "Copy"}
          </Button>
        </div>

        <div className="flex flex-wrap gap-2">
          {shareIntents.map((intent) => (
            <Button
              key={intent.label}
              asChild
              variant="outline"
              size="sm"
            >
              <a href={intent.href} target="_blank" rel="noopener noreferrer">
                <HugeiconsIcon icon={intent.icon} size={16} />
                {intent.label}
              </a>
            </Button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
