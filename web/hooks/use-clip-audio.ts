"use client"

import { useEffect, useRef, useState } from "react"

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
 * Fetches through the authed same-origin proxy and re-decodes when the id
 * changes; the in-flight decode is aborted on change/unmount. The outcome is
 * tagged with its clip id, so a result whose id no longer matches the requested
 * one reads as "loading" — no stale audio flashes under a new id, and no
 * synchronous setState is needed to reset between clips.
 *
 * Keyed on token *presence*, not identity: the access token now rotates
 * mid-session (auth refresh-ahead, #285), and re-decoding the whole clip on
 * every rotation would be pure wasted network+CPU (the buffer is read once).
 * The latest token is read from a ref so a rotation doesn't retrigger the
 * decode, while a null→token transition still kicks off the initial load.
 */
export function useClipAudio(
  clipId: string | undefined,
  token: string | null
): ClipAudioState {
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  // Latest token kept in a ref (updated in an effect, not during render) so the
  // decode effect can read it without listing `token` as a dep — a rotation
  // updates the ref but doesn't retrigger the decode.
  const tokenRef = useRef(token)
  useEffect(() => {
    tokenRef.current = token
  }, [token])
  const hasToken = token !== null

  useEffect(() => {
    if (!clipId || !tokenRef.current) return
    const ctl = new AbortController()
    decodeClipAudio(clipId, tokenRef.current, ctl.signal)
      .then((audio) => {
        if (!ctl.signal.aborted) setOutcome({ id: clipId, kind: "ready", audio })
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOutcome({ id: clipId, kind: "error" })
      })
    return () => ctl.abort()
  }, [clipId, hasToken])

  const current = outcome?.id === clipId ? outcome : null
  if (!current) return { status: "loading" }
  return current.kind === "ready"
    ? { status: "ready", audio: current.audio }
    : { status: "error" }
}
