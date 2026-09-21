"use client"

import { useContext, useState, type ReactNode } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Flag02Icon } from "@hugeicons/core-free-icons"

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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { AuthContext } from "@/contexts/auth-context"
import {
  REPORT_CATEGORIES,
  submitClipReport,
  type ReportCategory,
} from "@/lib/reports"

// "Report" control for any public clip surface (US-27.2). Renders nothing for a
// signed-out viewer or the clip's owner. Reads AuthContext directly (not useAuth)
// so surfaces rendered outside an AuthProvider simply show no Report control.
// The confirmation is shown inside the dialog — the repo has no toast layer.

type Phase =
  | { kind: "form"; error?: string }
  | { kind: "submitting" }
  | { kind: "done"; message: string }

export function ReportClipButton({
  clipId,
  isOwner = false,
  trigger,
}: {
  clipId: string
  isOwner?: boolean
  /** Custom trigger (e.g. the feed's rail button); defaults to a ghost icon button. */
  trigger?: (open: () => void) => ReactNode
}) {
  const auth = useContext(AuthContext)
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState<ReportCategory | "">("")
  const [details, setDetails] = useState("")
  const [phase, setPhase] = useState<Phase>({ kind: "form" })

  if (!auth?.isAuthenticated || !auth.accessToken || isOwner) return null
  const accessToken = auth.accessToken

  const show = () => {
    setCategory("")
    setDetails("")
    setPhase({ kind: "form" })
    setOpen(true)
  }

  const submit = async () => {
    if (!category) return
    setPhase({ kind: "submitting" })
    const result = await submitClipReport(
      clipId,
      category,
      details,
      accessToken
    )
    setPhase(
      result.status === "received"
        ? { kind: "done", message: result.message }
        : { kind: "form", error: result.detail }
    )
  }

  return (
    <>
      {trigger ? (
        trigger(show)
      ) : (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Report"
          onClick={show}
        >
          <HugeiconsIcon icon={Flag02Icon} size={18} />
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Report clip</DialogTitle>
            <DialogDescription>
              Tell us what&apos;s wrong. Reports go to our moderation team.
            </DialogDescription>
          </DialogHeader>

          {phase.kind === "done" ? (
            <>
              <p role="status" className="text-sm">
                {phase.message}
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
              <RadioGroup
                value={category}
                onValueChange={(v) => setCategory(v as ReportCategory)}
                aria-label="Reason"
              >
                {REPORT_CATEGORIES.map((c) => (
                  <div key={c.value} className="flex items-center gap-2">
                    <RadioGroupItem id={`report-${c.value}`} value={c.value} />
                    <Label htmlFor={`report-${c.value}`}>{c.label}</Label>
                  </div>
                ))}
              </RadioGroup>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="report-details">Details (optional)</Label>
                <Textarea
                  id="report-details"
                  value={details}
                  onChange={(e) => setDetails(e.target.value)}
                  maxLength={1000}
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
                  disabled={!category || phase.kind === "submitting"}
                >
                  Submit report
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
