"use client"

import { useEffect, useMemo, useRef } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitExtend } from "@/lib/editing"
import type { Section } from "@/lib/song-structure"

// Step 2 of the wizard (US-17.4): generate one section by extending the current
// cumulative clip. Reuses useClipEdit — the same epoch-guarded submit→poll→
// success/error machine the editing modals use — so retries, the poll cap, and
// 401/402/422 classification all come for free. On success it reports the new
// clip id up; the flow reducer decides what happens next. One extend per mount
// (the flow remounts this between sections/regenerations).

export function SectionGenerationStep({
  cumulativeClipId,
  section,
  baseStyle,
  instructions,
  accessToken,
  sectionNumber,
  totalSections,
  onComplete,
}: {
  cumulativeClipId: string
  section: Section
  /** The seed clip's own style, kept so each section stays stylistically coherent. */
  baseStyle: string
  /** Extra steering from a rejected section's regeneration, if any. */
  instructions: string
  accessToken: string | null
  sectionNumber: number
  totalSections: number
  onComplete: (clipId: string) => void
}) {
  const { state, submit } = useClipEdit()
  const startedRef = useRef(false)
  const completedRef = useRef(false)

  // base style + section emphasis + any regeneration note → one style_override.
  const styleOverride = useMemo(
    () =>
      [baseStyle, section.styleHint, instructions]
        .map((s) => (s ?? "").trim())
        .filter(Boolean)
        .join(", "),
    [baseStyle, section.styleHint, instructions]
  )

  function run() {
    if (!accessToken) return
    completedRef.current = false
    void submit(
      () =>
        submitExtend(
          cumulativeClipId,
          {
            // Floor (not round) so the summed sections never push the cumulative
            // clip past the target — and thus never past the backend's cap.
            duration: `${Math.max(1, Math.floor(section.durationSeconds))}s`,
            from_point: "end",
            style_override: styleOverride,
          },
          accessToken
        ),
      accessToken
    )
  }

  // Kick off exactly one extend when this section starts generating. The flow
  // remounts the step per section/regeneration, so the mount guard resets. Wait
  // for the access token so a momentarily-unresolved auth state can't strand the
  // section spinning; once present we submit exactly once.
  useEffect(() => {
    if (startedRef.current || !accessToken) return
    startedRef.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken])

  // Hand the generated clip up once the job completes.
  useEffect(() => {
    if (state.phase === "success" && !completedRef.current) {
      completedRef.current = true
      const clipId = state.clipIds[0]
      if (clipId) onComplete(clipId)
    }
  }, [state, onComplete])

  const failed =
    state.phase === "error" ||
    (state.phase === "success" && state.clipIds.length === 0)

  return (
    <div className="flex flex-col gap-4 py-2">
      <div className="text-sm">
        <p className="font-medium">
          Section {sectionNumber} of {totalSections}:{" "}
          <span className="capitalize">{section.name}</span>
        </p>
        <p className="text-xs text-muted-foreground">{section.styleHint}</p>
      </div>

      {failed ? (
        <div className="flex flex-col gap-3">
          <p role="alert" className="text-sm text-destructive">
            {state.phase === "error"
              ? state.message
              : "The section came back empty. Please try again."}
          </p>
          <Button className="self-start" onClick={run}>
            Retry
          </Button>
        </div>
      ) : (
        <div
          role="status"
          className="flex items-center gap-2 py-4 text-sm text-muted-foreground"
        >
          <HugeiconsIcon
            icon={Loading03Icon}
            className="animate-spin"
            data-icon="inline-start"
          />
          <span>
            Generating {section.name}…
            {state.phase === "polling" && state.estimatedSeconds > 0
              ? ` ~${state.estimatedSeconds}s`
              : ""}
          </span>
          {state.phase === "polling" && state.progress && (
            <span className="text-xs">{state.progress}</span>
          )}
        </div>
      )}
    </div>
  )
}
