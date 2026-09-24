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
  addAppealContext,
  submitClipAppeal,
  type AppealView,
} from "@/lib/appeals"
import type { Clip } from "@/lib/workspace-clips"

// Moderation status + appeal entry point for a single clip card (US-27.4).
// Renders nothing for a clip that was never moderated and has no appeal
// history. Reads AuthContext directly (not useAuth) so a card rendered outside
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
  clip: Pick<Clip, "id" | "removed_at" | "content_warning">
  /** The caller's latest appeal against this clip's current (or most recent) decision. */
  appeal: AppealView | null
}) {
  const auth = useContext(AuthContext)
  const [override, setOverride] = useState<AppealView | null>(null)
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [context, setContext] = useState("")
  const [phase, setPhase] = useState<Phase>({ kind: "form" })
  const [doneMessage, setDoneMessage] = useState<string | null>(null)
  const [infoContext, setInfoContext] = useState("")
  const [infoPhase, setInfoPhase] = useState<Phase>({ kind: "form" })
  const [infoDone, setInfoDone] = useState<string | null>(null)

  const current = override ?? appeal
  const removed = clip.removed_at != null
  const flagged = clip.content_warning === true
  if (!removed && !flagged && !current) return null

  const canAppeal =
    !!auth?.isAuthenticated &&
    !!auth.accessToken &&
    (removed || flagged) &&
    // An appeal only blocks the decision it was filed against; a later removal is a new one.
    (!current ||
      current.status === "reversed" ||
      current.action !== (removed ? "remove" : "flag"))
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
    const result = await submitClipAppeal(clip.id, reason, context, accessToken)
    if (result.status === "submitted") {
      setOverride(result.appeal)
      setDoneMessage(result.message)
      setPhase({ kind: "form" })
    } else {
      setPhase({ kind: "form", error: result.detail })
    }
  }

  async function sendMoreInfo() {
    if (!accessToken || !infoContext.trim()) return
    setInfoPhase({ kind: "submitting" })
    const result = await addAppealContext(clip.id, infoContext, accessToken)
    if (result.status === "submitted") {
      setOverride(result.appeal)
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

      {current?.status === "pending" && (
        <p className="text-xs text-muted-foreground">{STATUS_LABEL.pending}</p>
      )}

      {current?.status === "upheld" && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs text-muted-foreground">{STATUS_LABEL.upheld}</p>
          {current.admin_note && (
            <p className="text-xs text-muted-foreground italic">
              {current.admin_note}
            </p>
          )}
        </div>
      )}

      {current?.status === "reversed" && (
        <p role="status" className="text-xs text-muted-foreground">
          {STATUS_LABEL.reversed}
        </p>
      )}

      {infoDone && (
        <p role="status" className="text-xs text-muted-foreground">
          {infoDone}
        </p>
      )}

      {!infoDone && current?.status === "info_requested" && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-muted-foreground">
            {STATUS_LABEL.info_requested}
          </p>
          {current.admin_note && (
            <p className="text-xs text-muted-foreground italic">
              {current.admin_note}
            </p>
          )}
          <form
            className="flex flex-col gap-1.5"
            onSubmit={(e) => {
              e.preventDefault()
              void sendMoreInfo()
            }}
          >
            <Label htmlFor={`appeal-more-info-${clip.id}`}>
              Additional context
            </Label>
            <Textarea
              id={`appeal-more-info-${clip.id}`}
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
