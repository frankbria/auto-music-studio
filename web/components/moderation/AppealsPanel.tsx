"use client"

import { useCallback, useEffect, useState } from "react"

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
import {
  decideAppeal,
  fetchAppeals,
  parseApiTime,
  type AppealDecision,
  type AppealQueueItem,
  type AppealStatusFilter,
} from "@/lib/moderation"

// Admin appeals queue (US-27.4): open (default) or all appeals against a
// removal/flag decision, with Uphold / Reverse / Request info actions. Every
// decision refetches the list rather than patching it locally.

const ACTION_LABEL: Record<AppealQueueItem["action"], string> = {
  remove: "Removed",
  flag: "Flagged",
}

const STATUS_LABEL: Record<AppealQueueItem["status"], string> = {
  pending: "Pending",
  info_requested: "Info requested",
  upheld: "Upheld",
  reversed: "Reversed",
}

const PAST_VERB: Record<AppealDecision, string> = {
  uphold: "Upheld",
  reverse: "Reversed",
  request_info: "Requested more information for",
}

const DECISION_COPY: Record<
  AppealDecision,
  { verb: string; description: string; noteRequired: boolean }
> = {
  uphold: {
    verb: "Uphold",
    description: "The original decision stands. The creator is notified.",
    noteRequired: false,
  },
  reverse: {
    verb: "Reverse",
    description:
      "The clip's removal or flag is cleared. The creator is notified.",
    noteRequired: false,
  },
  request_info: {
    verb: "Request info",
    description:
      "Ask the creator for more detail before deciding. Explain what's missing.",
    noteRequired: true,
  },
}

const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}

function clipLabel(item: AppealQueueItem) {
  return item.clip_deleted
    ? "Clip deleted"
    : (item.clip_title ?? "Untitled clip")
}

function formatTime(iso: string) {
  const date = parseApiTime(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

type Confirming = { appeal: AppealQueueItem; decision: AppealDecision }

export function AppealsPanel({ accessToken }: { accessToken: string | null }) {
  const [status, setStatus] = useState<AppealStatusFilter>("open")
  const [appeals, setAppeals] = useState<AppealQueueItem[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<Confirming | null>(null)
  const [note, setNote] = useState("")

  const load = useCallback(() => {
    if (!accessToken) return
    void fetchAppeals(accessToken, status)
      .then((next) => {
        setAppeals(next)
        setLoadError(null)
      })
      .catch((error) => setLoadError(errorMessage(error)))
  }, [accessToken, status])

  useEffect(() => {
    load()
  }, [load])

  function openDecision(appeal: AppealQueueItem, decision: AppealDecision) {
    setNote("")
    setConfirming({ appeal, decision })
  }

  async function confirm() {
    if (!confirming || !accessToken) return
    const { appeal, decision } = confirming
    setBusy(true)
    setNotice(null)
    setConfirming(null)
    try {
      await decideAppeal(accessToken, appeal.id, decision, note)
      setNotice(`${PAST_VERB[decision]} appeal for ${clipLabel(appeal)}.`)
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
    load()
  }

  const copy = confirming ? DECISION_COPY[confirming.decision] : undefined

  return (
    <div className="flex flex-col gap-4" data-slot="appeals-panel">
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Label htmlFor="appeals-status">Show</Label>
        <select
          id="appeals-status"
          className={selectClass}
          value={status}
          onChange={(e) => setStatus(e.target.value as AppealStatusFilter)}
        >
          <option value="open">Open appeals</option>
          <option value="all">All appeals</option>
        </select>
      </div>

      {loadError ? (
        <p role="alert" className="text-sm text-destructive">
          {loadError}
        </p>
      ) : appeals === null ? (
        <p className="text-sm text-muted-foreground">Loading appeals...</p>
      ) : appeals.length === 0 ? (
        <p className="text-sm text-muted-foreground">No appeals to review.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {appeals.map((item) => {
            const open = item.decided_at === null
            return (
              <div
                key={item.id}
                className="flex flex-col gap-2 rounded-lg border border-border p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-medium">{clipLabel(item)}</span>
                    <span className="text-xs text-muted-foreground">
                      {item.creator_name ?? "-"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Badge variant="destructive">
                      {ACTION_LABEL[item.action]}
                    </Badge>
                    <Badge variant="outline">{STATUS_LABEL[item.status]}</Badge>
                  </div>
                </div>
                {item.action_reason && (
                  <p className="text-xs text-muted-foreground">
                    Moderation reason: {item.action_reason}
                  </p>
                )}
                <p className="text-sm">{item.reason}</p>
                {item.context && (
                  <p className="text-sm text-muted-foreground">
                    Context: {item.context}
                  </p>
                )}
                {item.admin_note && (
                  <p className="text-xs text-muted-foreground italic">
                    Admin note: {item.admin_note}
                  </p>
                )}
                <span className="text-xs text-muted-foreground">
                  Submitted {formatTime(item.created_at)}
                </span>
                {open && (
                  <div className="flex flex-wrap gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => openDecision(item, "uphold")}
                    >
                      Uphold
                    </Button>
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => openDecision(item, "reverse")}
                    >
                      Reverse
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => openDecision(item, "request_info")}
                    >
                      Request info
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <Dialog
        open={confirming !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setConfirming(null)
        }}
      >
        <DialogContent>
          {confirming && copy && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {copy.verb} appeal for {clipLabel(confirming.appeal)}?
                </DialogTitle>
                <DialogDescription>{copy.description}</DialogDescription>
              </DialogHeader>
              <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                  e.preventDefault()
                  void confirm()
                }}
              >
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="appeal-decision-note">
                    Note {copy.noteRequired ? "" : "(optional)"}
                  </Label>
                  <Textarea
                    id="appeal-decision-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={1000}
                    rows={3}
                  />
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setConfirming(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={copy.noteRequired && !note.trim()}
                  >
                    {copy.verb}
                  </Button>
                </DialogFooter>
              </form>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
