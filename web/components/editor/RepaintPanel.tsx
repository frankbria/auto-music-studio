"use client"

import { useEffect, useRef, useState } from "react"

import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { StyleTextarea } from "@/components/song/modals/StyleTextarea"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { decodeClipAudio, type ClipAudio } from "@/lib/audio-peaks"
import { PROMPT_MAX_LENGTH, STYLE_MAX_LENGTH } from "@/lib/constants/generation"
import { submitRepaint } from "@/lib/editing"
import type { EditOperation, Region } from "@/lib/waveform-edit"

// Repaint panel for the waveform editor (US-18.5). Appears while a region is
// selected: the musician writes new instructions and regenerates just that
// section with AI. It reuses the Stage-17 repaint pipeline wholesale —
// `submitRepaint` + `useClipEdit`'s submit→poll job lifecycle — and only adds
// the editor-side glue: the selected region *is* the range, and the result is
// folded back into the editor's own undo stack.
//
// On completion the backend has produced a full, crossfade-blended child clip
// (US-6.3) with only [start,end] regenerated. We decode that child and hand it
// up as a normal edit snapshot (`onRepainted`), so the existing Undo/Redo covers
// repaint for free rather than needing a separate navigation-based undo. The
// selected region's readout is the editor's own SelectionInfo, rendered directly
// above this panel — no need to duplicate it here.

type RepaintSubmitted = { prompt: string; style?: string; startSec: number; endSec: number }

export function RepaintPanel({
  selection,
  clipId,
  onRepainted,
}: {
  selection: Region
  clipId: string
  onRepainted: (audio: ClipAudio, op: EditOperation) => void
}) {
  const { accessToken } = useAuth()
  const edit = useClipEdit()
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")
  // The backend job is done but we still have to fetch + decode the child clip's
  // audio before it can be shown; a distinct phase so the spinner stays up.
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)

  // What we actually submitted, so the recorded op + decode target don't drift if
  // the fields change during the async job.
  const submittedRef = useRef<RepaintSubmitted | null>(null)
  // One-shot guard: `useClipEdit`'s success state persists across the frequent
  // re-renders the player's time-tick drives, so the decode must run exactly once.
  const appliedRef = useRef(false)
  // `onRepainted` in a ref so a changing parent closure doesn't re-arm the apply
  // effect (which would cancel an in-flight decode and drop the result).
  const onRepaintedRef = useRef(onRepainted)
  useEffect(() => {
    onRepaintedRef.current = onRepainted
  })
  const mountedRef = useRef(true)
  useEffect(() => () => void (mountedRef.current = false), [])

  const overPrompt = prompt.length > PROMPT_MAX_LENGTH
  const overStyle = style.length > STYLE_MAX_LENGTH
  const valid = prompt.trim().length > 0 && !overPrompt && !overStyle

  const busy = edit.state.phase === "submitting" || edit.state.phase === "polling" || applying
  const errorMsg =
    applyError ?? (edit.state.phase === "error" ? edit.state.message : null)

  function handleSubmit() {
    if (!accessToken || !valid) return
    appliedRef.current = false
    setApplyError(null)
    const p = prompt.trim()
    const s = style.trim()
    submittedRef.current = {
      prompt: p,
      style: s || undefined,
      startSec: selection.startSec,
      endSec: selection.endSec,
    }
    const payload = { start: `${selection.startSec}s`, end: `${selection.endSec}s`, prompt: p, ...(s ? { style: s } : {}) }
    void edit.submit(() => submitRepaint(clipId, payload, accessToken), accessToken)
  }

  // When the job completes, pull the child clip's audio and hand it up as a
  // repaint snapshot. Keyed on the job state (not on the parent closure), guarded
  // one-shot; the parent clearing the selection through pushEdit unmounts us.
  useEffect(() => {
    if (edit.state.phase !== "success" || appliedRef.current) return
    appliedRef.current = true
    const childId = edit.state.clipIds[0]
    const submitted = submittedRef.current
    if (!childId || !accessToken || !submitted) {
      setApplyError("Repaint finished but returned no clip.")
      return
    }
    setApplying(true)
    decodeClipAudio(childId, accessToken)
      .then((audio) => {
        const op: EditOperation = {
          kind: "repaint",
          startSec: submitted.startSec,
          endSec: submitted.endSec,
          prompt: submitted.prompt,
          ...(submitted.style ? { style: submitted.style } : {}),
        }
        onRepaintedRef.current(audio, op)
      })
      .catch(() => {
        if (!mountedRef.current) return
        setApplying(false)
        setApplyError("Couldn't load the repainted audio. Please try again.")
      })
  }, [edit.state, accessToken])

  return (
    <div
      data-testid="repaint-panel"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3"
    >
      <h2 className="text-sm font-semibold">Repaint selection</h2>

      {busy ? (
        <div role="status" className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
          <HugeiconsIcon icon={Loading03Icon} className="animate-spin" data-icon="inline-start" />
          <span>
            {applying ? "Applying…" : "Regenerating…"}
            {edit.state.phase === "polling" && edit.state.estimatedSeconds > 0
              ? ` ~${edit.state.estimatedSeconds}s`
              : ""}
          </span>
          {edit.state.phase === "polling" && edit.state.progress && (
            <span className="text-xs">{edit.state.progress}</span>
          )}
        </div>
      ) : errorMsg ? (
        <div className="flex flex-col gap-2">
          <p role="alert" className="text-sm text-destructive">
            {errorMsg}
          </p>
          <div>
            <Button type="button" size="sm" onClick={handleSubmit} disabled={!valid}>
              Try again
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <StyleTextarea
            label="Instructions"
            value={prompt}
            onChange={setPrompt}
            placeholder="Describe how to regenerate this section…"
            maxLength={PROMPT_MAX_LENGTH}
            required
          />
          <StyleTextarea
            label="Style (optional)"
            value={style}
            onChange={setStyle}
            placeholder="e.g. lofi, orchestral"
            maxLength={STYLE_MAX_LENGTH}
            rows={2}
          />
          <div>
            <Button type="button" size="sm" onClick={handleSubmit} disabled={!valid}>
              Regenerate
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
