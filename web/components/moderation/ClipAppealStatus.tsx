"use client"

import { useContext, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { AuthContext } from "@/contexts/auth-context"
import {
  addContext,
  submitAppeal,
  type AppealTarget,
  type AppealView,
} from "@/lib/appeals"
import type { Clip } from "@/lib/workspace-clips"

// Moderation status + appeal entry point for a single clip card (US-27.4), or
// a taken-down video (#623). Renders nothing for a clip that was never
// moderated and has no appeal history. Reads AuthContext directly (not useAuth) so a card rendered outside
// an AuthProvider just shows the read-only status, no interactive controls.

type Phase = { kind: "form"; error?: string } | { kind: "submitting" }

const STATUS_LABEL: Record<AppealView["status"], string> = {
  pending: "Appeal pending",
  info_requested: "More information requested",
  upheld: "Appeal denied",
  reversed: "Appeal approved",
}

export function ClipAppealStatus({
  clip,
  appeal,
}: {
  clip: Pick<Clip, "id" | "removed_at" | "content_warning" | "flagged_at">
  /** The caller's latest appeal against this clip's current (or most recent) decision. */
  appeal: AppealView | null
}) {
  const removed = clip.removed_at != null
  return (
    <ModerationAppealStatus
      target={{ kind: "clip", id: clip.id }}
      removed={removed}
      flagged={clip.content_warning === true}
      decidedAt={(removed ? clip.removed_at : clip.flagged_at) ?? null}
      appeal={appeal}
    />
  )
}

/** A video moderation took down (#623); the caller only renders it for one. */
export function VideoAppealStatus({
  videoId,
  appeal,
}: {
  videoId: string
  /** The caller's latest appeal against this video's unpublishes. */
  appeal: AppealView | null
}) {
  return (
    <ModerationAppealStatus
      target={{ kind: "video", id: videoId }}
      removed
      flagged={false}
      decidedAt={null}
      appeal={appeal}
    />
  )
}

function ModerationAppealStatus({
  target,
  removed,
  flagged,
  decidedAt,
  appeal,
}: {
  target: AppealTarget
  removed: boolean
  flagged: boolean
  /** When the decision in force was made, if known: an appeal older than it is against an earlier one. */
  decidedAt: string | null
  appeal: AppealView | null
}) {
  const auth = useContext(AuthContext)
  // What this card last submitted, and the `appeal` prop it replaced. A refetch
  // hands down a new prop object, which supersedes it (#543).
  const [override, setOverride] = useState<{
    over: AppealView | null
    value: AppealView
  } | null>(null)
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [context, setContext] = useState("")
  const [phase, setPhase] = useState<Phase>({ kind: "form" })
  const [doneMessage, setDoneMessage] = useState<string | null>(null)
  const [infoContext, setInfoContext] = useState("")
  const [infoPhase, setInfoPhase] = useState<Phase>({ kind: "form" })
  const [infoDone, setInfoDone] = useState<string | null>(null)

  const current = override?.over === appeal ? override.value : appeal
  if (!removed && !flagged && !current) return null

  // An appeal only blocks the decision it was filed against. A later removal
  // restamps removed_at, and a re-flag flagged_at (#543), so a decision newer
  // than the appeal is a new one.
  const removalAction = target.kind === "video" ? "unpublish" : "remove"
  const coversCurrentDecision =
    !!current &&
    current.action === (removed ? removalAction : "flag") &&
    !(
      decidedAt != null &&
      new Date(decidedAt).getTime() > new Date(current.created_at).getTime()
    )
  // A resolved appeal's outcome only describes the clip while no newer decision
  // is in force; a reversal is still shown after the clip has been cleared.
  const shownStatus =
    coversCurrentDecision || (!removed && !flagged)
      ? current?.status
      : undefined
  const canAppeal =
    !!auth?.isAuthenticated &&
    !!auth.accessToken &&
    (removed || flagged) &&
    (!coversCurrentDecision || current?.status === "reversed")
  const accessToken = auth?.accessToken ?? null

  const show = () => {
    setReason("")
    setContext("")
    setPhase({ kind: "form" })
    setDoneMessage(null)
    setOpen(true)
  }

  async function submit() {
    if (!accessToken || !reason.trim()) return
    setPhase({ kind: "submitting" })
    const result = await submitAppeal(target, reason, context, accessToken)
    if (result.status === "submitted") {
      setOverride({ over: appeal, value: result.appeal })
      setDoneMessage(result.message)
      setPhase({ kind: "form" })
    } else {
      setPhase({ kind: "form", error: result.detail })
    }
  }

  async function sendMoreInfo() {
    if (!accessToken || !infoContext.trim()) return
    setInfoPhase({ kind: "submitting" })
    const result = await addContext(target, infoContext, accessToken)
    if (result.status === "submitted") {
      setOverride({ over: appeal, value: result.appeal })
      setInfoDone(result.message)
      setInfoPhase({ kind: "form" })
      setInfoContext("")
    } else {
      setInfoPhase({ kind: "form", error: result.detail })
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        {removed && <Badge variant="destructive">Removed by moderation</Badge>}
        {flagged && <Badge variant="destructive">Content warning</Badge>}
        {canAppeal && (
          <Button variant="outline" size="sm" onClick={show}>
            Appeal
          </Button>
        )}
      </div>

      {shownStatus === "pending" && (
        <p className="text-xs text-muted-foreground">{STATUS_LABEL.pending}</p>
      )}

      {shownStatus === "upheld" && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs text-muted-foreground">{STATUS_LABEL.upheld}</p>
          {current?.admin_note && (
            <p className="text-xs text-muted-foreground italic">
              {current?.admin_note}
            </p>
          )}
        </div>
      )}

      {shownStatus === "reversed" && (
        <p role="status" className="text-xs text-muted-foreground">
          {STATUS_LABEL.reversed}
        </p>
      )}

      {infoDone && (
        <p role="status" className="text-xs text-muted-foreground">
          {infoDone}
        </p>
      )}

      {!infoDone && shownStatus === "info_requested" && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-muted-foreground">
            {STATUS_LABEL.info_requested}
          </p>
          {current?.admin_note && (
            <p className="text-xs text-muted-foreground italic">
              {current?.admin_note}
            </p>
          )}
          <form
            className="flex flex-col gap-1.5"
            onSubmit={(e) => {
              e.preventDefault()
              void sendMoreInfo()
            }}
          >
            <Label htmlFor={`appeal-more-info-${target.kind}-${target.id}`}>
              Additional context
            </Label>
            <Textarea
              id={`appeal-more-info-${target.kind}-${target.id}`}
              value={infoContext}
              onChange={(e) => setInfoContext(e.target.value)}
              maxLength={2000}
              rows={2}
            />
            {infoPhase.kind === "form" && infoPhase.error && (
              <p role="alert" className="text-xs text-destructive">
                {infoPhase.error}
              </p>
            )}
            <Button
              type="submit"
              size="sm"
              className="self-start"
              disabled={!infoContext.trim() || infoPhase.kind === "submitting"}
            >
              Send
            </Button>
          </form>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Appeal moderation decision</DialogTitle>
            <DialogDescription>
              Tell us why this decision should be reconsidered.
            </DialogDescription>
          </DialogHeader>

          {doneMessage ? (
            <>
              <p role="status" className="text-sm">
                {doneMessage}
              </p>
              <DialogFooter>
                <Button onClick={() => setOpen(false)}>Close</Button>
              </DialogFooter>
            </>
          ) : (
            <form
              className="flex flex-col gap-4"
              onSubmit={(e) => {
                e.preventDefault()
                void submit()
              }}
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="appeal-reason">Reason for appeal</Label>
                <Textarea
                  id="appeal-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={2000}
                  rows={3}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="appeal-context">
                  Supporting context (optional)
                </Label>
                <Textarea
                  id="appeal-context"
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  maxLength={2000}
                  rows={3}
                />
              </div>
              {phase.kind === "form" && phase.error && (
                <p role="alert" className="text-sm text-destructive">
                  {phase.error}
                </p>
              )}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={!reason.trim() || phase.kind === "submitting"}
                >
                  Submit appeal
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
