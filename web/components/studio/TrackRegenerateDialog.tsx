"use client"

import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useStudio, type StudioTrack } from "@/contexts/studio-context"
import { useGeneration } from "@/hooks/use-generation"
import { submitGeneration, submitSoundsGeneration } from "@/lib/generate"
import { placementPlaybackRate } from "@/lib/track-types"
import type { Clip } from "@/lib/workspace-clips"

// AI Regenerate for a studio track (US-19.4): prompt → existing /api/generate
// pipeline (submit + poll via useGeneration) → the finished clip is fetched and
// APPENDED to the track after its last clip — regeneration is additive, like
// every other lineage operation in this app; nothing is replaced. The request's
// mode follows the track type (loop → sound/loop, ai → song) so the resulting
// clip's inferred type passes ADD_CLIP's strict type check.

/** Timeline second where an appended clip starts: the end of the last clip. */
function appendStartSec(track: StudioTrack, projectBpm: number): number {
  return track.clips.reduce((end, c) => {
    const rate = placementPlaybackRate(c.clipBpm, track.trackType, projectBpm)
    return Math.max(end, c.startSec + (c.durationSec ?? 0) / rate)
  }, 0)
}

export function TrackRegenerateDialog({
  track,
  token,
  onClose,
}: {
  track: StudioTrack
  token: string | null
  onClose: () => void
}) {
  const { state, dispatch } = useStudio()
  const { state: gen, submit } = useGeneration()
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")
  const addedRef = useRef(false)

  const busy = gen.phase === "submitting" || gen.phase === "polling"

  function handleGenerate() {
    const trimmed = prompt.trim()
    if (!token || !trimmed || busy) return
    if (track.trackType === "loop") {
      void submit(
        () =>
          submitSoundsGeneration(
            {
              description: trimmed,
              soundType: "loop",
              bpmAuto: false,
              bpm: String(state.bpm),
              key: "",
            },
            token
          ),
        token
      )
    } else {
      void submit(
        () =>
          submitGeneration(
            {
              description: trimmed,
              lyrics: "",
              instrumental: false,
              selectedTags: style.trim() ? [style.trim()] : [],
            },
            token
          ),
        token
      )
    }
  }

  // On success, fetch the new clip's metadata and append it to this track. The
  // dispatch happens in the fetch's async callback (not synchronously in the
  // effect body), then the dialog closes.
  const startSec = appendStartSec(track, state.bpm)
  useEffect(() => {
    if (gen.phase !== "success" || addedRef.current || !token) return
    const clipId = gen.clipIds[0]
    if (!clipId) return
    addedRef.current = true
    let active = true
    fetch(`/api/clips/${encodeURIComponent(clipId)}`, {
      headers: { authorization: `Bearer ${token}` },
    })
      .then(async (res) => (res.ok ? ((await res.json()) as Clip) : null))
      .then((clip) => {
        if (!active || !clip) return
        dispatch({
          type: "ADD_CLIP",
          id: crypto.randomUUID(),
          trackId: track.id,
          clipId: clip.id,
          startSec,
          title: clip.title,
          durationSec: clip.duration,
          generationMode: clip.generation_mode,
          clipBpm: clip.bpm,
        })
        onClose()
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gen, token])

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Regenerate track</DialogTitle>
          <DialogDescription>
            Generate a new clip for “{track.name}” and add it to the end of the
            track.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="regen-prompt">Prompt</Label>
            <Textarea
              id="regen-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                track.trackType === "loop"
                  ? "Describe the loop — e.g. punchy four-on-the-floor drum loop"
                  : "Describe what to generate — e.g. dreamy synth chorus"
              }
              disabled={busy}
            />
          </div>
          {track.trackType !== "loop" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="regen-style">Style (optional)</Label>
              <Input
                id="regen-style"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                placeholder="e.g. synthwave, ambient"
                disabled={busy}
              />
            </div>
          )}
          {gen.phase === "polling" && (
            <p className="text-sm text-muted-foreground" role="status">
              Generating…{" "}
              {gen.estimatedSeconds > 0 && `~${gen.estimatedSeconds}s`}{" "}
              {gen.progress}
            </p>
          )}
          {gen.phase === "success" && (
            <p className="text-sm text-muted-foreground" role="status">
              Adding clip to the track…
            </p>
          )}
          {gen.phase === "error" && (
            <p className="text-sm text-destructive" role="alert">
              {gen.message}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleGenerate}
            disabled={!prompt.trim() || busy || !token}
          >
            {busy ? "Generating…" : "Generate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
