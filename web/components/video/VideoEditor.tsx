"use client"

import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/hooks/use-auth"
import {
  editOperationLabel,
  fetchVideoVersions,
  submitVideoEdit,
  videoStreamUrl,
  type VideoEditOperation,
  type VideoEditPayload,
  type VideoVersion,
} from "@/lib/video"

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "queued" }
  | { status: "error"; message: string }

const OPERATIONS: { value: VideoEditOperation; label: string }[] = [
  { value: "trim", label: "Trim" },
  { value: "replace_scene", label: "Replace a scene" },
  { value: "lyrics_overlay", label: "Lyrics overlay" },
  { value: "transitions", label: "Transition timing" },
]

/** Parse a positive-number field, returning null when blank/invalid. */
function num(value: string): number | null {
  if (value.trim() === "") return null
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/**
 * Non-destructive video editing (US-22.4): pick an edit operation, submit it
 * (each produces a new version — the source is never touched), and see the full
 * edit history. Rendering runs on the provider, so a submitted edit shows as
 * "queued" and joins the version list once it finishes (Refresh re-fetches).
 */
export function VideoEditor({ videoId }: { videoId: string }) {
  const { accessToken } = useAuth()
  const [operation, setOperation] = useState<VideoEditOperation>("trim")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [prompt, setPrompt] = useState("")
  const [lyricsEnabled, setLyricsEnabled] = useState(true)
  const [markers, setMarkers] = useState("")
  const [submit, setSubmit] = useState<SubmitState>({ status: "idle" })
  const [versions, setVersions] = useState<VideoVersion[]>([])

  // Handler-side refresh (the button, and after a submit) — setState here is a
  // user/async callback, clear of the set-state-in-effect lint.
  const refreshVersions = useCallback(async () => {
    setVersions(await fetchVideoVersions(videoId, accessToken ?? ""))
  }, [videoId, accessToken])

  // Initial load: the fetch is inlined so the effect body never calls setState
  // synchronously (mirrors useClip); the `active` guard drops a stale response.
  useEffect(() => {
    let active = true
    fetchVideoVersions(videoId, accessToken ?? "").then((list) => {
      if (active) setVersions(list)
    })
    return () => {
      active = false
    }
  }, [videoId, accessToken])

  /** Build the typed payload for the chosen operation, or an error string. */
  function buildPayload(): VideoEditPayload | string {
    if (operation === "trim" || operation === "replace_scene") {
      const s = num(start)
      const e = num(end)
      if (s === null || e === null) return "Enter start and end times."
      if (e <= s) return "End must be after start."
      if (operation === "trim")
        return { operation, start_seconds: s, end_seconds: e }
      if (!prompt.trim()) return "Describe the replacement scene."
      return {
        operation,
        start_seconds: s,
        end_seconds: e,
        prompt: prompt.trim(),
      }
    }
    if (operation === "lyrics_overlay") {
      return { operation, lyrics_enabled: lyricsEnabled }
    }
    const parsed = markers
      .split(",")
      .map((m) => m.trim())
      .filter((m) => m !== "")
      .map(Number)
    if (
      parsed.length === 0 ||
      parsed.some((m) => !Number.isFinite(m) || m < 0)
    ) {
      return "Enter one or more non-negative marker times (comma-separated)."
    }
    return { operation, transition_markers: parsed }
  }

  async function handleSubmit() {
    const payload = buildPayload()
    if (typeof payload === "string") {
      setSubmit({ status: "error", message: payload })
      return
    }
    setSubmit({ status: "submitting" })
    const result = await submitVideoEdit(videoId, payload, accessToken ?? "")
    switch (result.status) {
      case "accepted":
        setSubmit({ status: "queued" })
        void refreshVersions()
        return
      case "unauthorized":
        setSubmit({ status: "error", message: "Please sign in again to edit." })
        return
      case "insufficient_credits":
        setSubmit({
          status: "error",
          message: `Not enough credits — ${result.required} required, ${result.balance} available.`,
        })
        return
      case "invalid":
      case "unavailable":
      case "error":
        setSubmit({ status: "error", message: result.detail })
        return
    }
  }

  const rangeOp = operation === "trim" || operation === "replace_scene"

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3" aria-label="Edit video">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="edit-operation">Edit</Label>
          <select
            id="edit-operation"
            className="h-9 rounded-md border bg-transparent px-3 text-sm"
            value={operation}
            onChange={(e) => {
              setOperation(e.target.value as VideoEditOperation)
              setSubmit({ status: "idle" })
            }}
          >
            {OPERATIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {rangeOp && (
          <div className="flex flex-wrap gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="edit-start">Start (s)</Label>
              <Input
                id="edit-start"
                type="number"
                min={0}
                step="0.1"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="w-28"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="edit-end">End (s)</Label>
              <Input
                id="edit-end"
                type="number"
                min={0}
                step="0.1"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="w-28"
              />
            </div>
          </div>
        )}

        {operation === "replace_scene" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-prompt">New scene prompt</Label>
            <Input
              id="edit-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="A slow zoom over city lights at night"
            />
          </div>
        )}

        {operation === "lyrics_overlay" && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={lyricsEnabled}
              onChange={(e) => setLyricsEnabled(e.target.checked)}
            />
            Show lyrics overlay (synced to the audio)
          </label>
        )}

        {operation === "transitions" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-markers">
              Cut points (seconds, comma-separated)
            </Label>
            <Input
              id="edit-markers"
              value={markers}
              onChange={(e) => setMarkers(e.target.value)}
              placeholder="4, 8.5, 12"
            />
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={submit.status === "submitting"}
          >
            {submit.status === "submitting" ? "Submitting…" : "Apply edit"}
          </Button>
          {submit.status === "queued" && (
            <p role="status" className="text-sm text-muted-foreground">
              Edit queued — it will appear below once rendered.
            </p>
          )}
          {submit.status === "error" && (
            <p role="alert" className="text-sm text-destructive">
              {submit.message}
            </p>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-2" aria-label="Version history">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Version history</h3>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void refreshVersions()}
          >
            Refresh
          </Button>
        </div>
        {versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No versions yet.</p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="version-list">
            {versions.map((v) => (
              <li
                key={v.id}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
              >
                <span className="flex flex-col">
                  <span className="font-medium">
                    {editOperationLabel(v.edit?.operation)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(v.created_at).toLocaleString()}
                  </span>
                </span>
                <span className="flex gap-2">
                  <Button asChild size="sm" variant="outline">
                    <a
                      href={videoStreamUrl(v.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View
                    </a>
                  </Button>
                  <Button asChild size="sm" variant="ghost">
                    <a href={videoStreamUrl(v.id, { download: true })} download>
                      Download
                    </a>
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
