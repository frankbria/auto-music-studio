"use client"

import { useEffect, useState } from "react"

import { decodeClipAudio, type ClipAudio } from "@/lib/audio-peaks"

export type ClipAudioState =
  | { status: "loading" }
  | { status: "ready"; audio: ClipAudio }
  | { status: "error" }

/** Decode outcome tagged with the clip id it belongs to (mirrors useClip). */
type Outcome =
  | { id: string; kind: "ready"; audio: ClipAudio }
  | { id: string; kind: "error" }

/**
 * Decode a clip's audio into peak data for the waveform editor (US-18.1).
 * Fetches through the authed same-origin proxy and re-decodes when the id or
 * token changes; the in-flight decode is aborted on change/unmount. The outcome
 * is tagged with its clip id, so a result whose id no longer matches the
 * requested one reads as "loading" — no stale audio flashes under a new id, and
 * no synchronous setState is needed to reset between clips.
 */
export function useClipAudio(
  clipId: string | undefined,
  token: string | null
): ClipAudioState {
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    if (!clipId || !token) return
    const ctl = new AbortController()
    decodeClipAudio(clipId, token, ctl.signal)
      .then((audio) => {
        if (!ctl.signal.aborted) setOutcome({ id: clipId, kind: "ready", audio })
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOutcome({ id: clipId, kind: "error" })
      })
    return () => ctl.abort()
  }, [clipId, token])

  const current = outcome?.id === clipId ? outcome : null
  if (!current) return { status: "loading" }
  return current.kind === "ready"
    ? { status: "ready", audio: current.audio }
    : { status: "error" }
}
