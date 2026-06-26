"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon, MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/use-auth"
import { submitGeneration } from "@/lib/generate"
import { InspirationTags } from "@/components/create/InspirationTags"

// A user-facing message only. Whether a request is in flight is tracked
// separately (isSubmitting) so a non-error notice — e.g. the +Audio placeholder
// — can't clobber the in-flight state and re-enable Create mid-request.
type Status =
  | { kind: "idle" }
  | { kind: "info"; message: string }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string }

/**
 * The Simple creation form (US-16.1): describe a song in plain language and go.
 * A controlled form whose Create button enables as soon as there's a description
 * or lyrics, then enqueues a generation request through the BFF proxy. Progress
 * and result rendering are deferred to US-16.7 — success just reports the job id.
 */
export function SimpleCreationForm() {
  const router = useRouter()
  const { accessToken } = useAuth()

  const [description, setDescription] = useState("")
  const [instrumental, setInstrumental] = useState(false)
  const [lyrics, setLyrics] = useState("")
  const [showLyrics, setShowLyrics] = useState(false)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [status, setStatus] = useState<Status>({ kind: "idle" })
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Lyrics only count when the field is open — hiding it shouldn't keep Create
  // enabled (and then submit an empty prompt). Use this one value everywhere.
  const effectiveLyrics = showLyrics ? lyrics : ""

  // Enabled the moment either text field has content — tags and the instrumental
  // toggle don't gate submission (per the acceptance criteria).
  const canSubmit =
    description.trim().length > 0 || effectiveLyrics.trim().length > 0

  async function handleCreate() {
    if (!canSubmit || isSubmitting) return
    if (!accessToken) {
      router.push("/login")
      return
    }
    setIsSubmitting(true)
    try {
      const result = await submitGeneration(
        { description, lyrics: effectiveLyrics, instrumental, selectedTags },
        accessToken
      )
      switch (result.status) {
        case "accepted":
          setStatus({
            kind: "success",
            message: "Generation started. We'll let you know when it's ready.",
          })
          break
        case "unauthorized":
          router.push("/login")
          break
        case "invalid":
        case "error":
          setStatus({ kind: "error", message: result.detail })
          break
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Label htmlFor="song-description">Song description</Label>
        <Textarea
          id="song-description"
          rows={4}
          placeholder="Describe the song you want to create..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {showLyrics && (
        <div className="flex flex-col gap-2">
          <Label htmlFor="song-lyrics">Lyrics</Label>
          <Textarea
            id="song-lyrics"
            rows={4}
            placeholder="Write your lyrics here..."
            value={lyrics}
            onChange={(e) => setLyrics(e.target.value)}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isSubmitting}
          onClick={() =>
            setStatus({ kind: "info", message: "Audio input is coming soon." })
          }
        >
          <HugeiconsIcon icon={MusicNote01Icon} data-icon="inline-start" />
          Audio
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-pressed={showLyrics}
          onClick={() => setShowLyrics((v) => !v)}
        >
          <HugeiconsIcon icon={Add01Icon} data-icon="inline-start" />
          Lyrics
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <Switch
            id="instrumental"
            checked={instrumental}
            onCheckedChange={setInstrumental}
          />
          <Label htmlFor="instrumental">Instrumental</Label>
        </div>
      </div>

      <InspirationTags selectedTags={selectedTags} onChange={setSelectedTags} />

      {/* Neutral notices (info/success) are polite status; only real failures
          use the assertive, destructive alert. */}
      {(status.kind === "info" || status.kind === "success") && (
        <p role="status" className="text-sm text-muted-foreground">
          {status.message}
        </p>
      )}
      {status.kind === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {status.message}
        </p>
      )}

      <Button
        type="button"
        className="w-fit"
        disabled={!canSubmit || isSubmitting}
        onClick={handleCreate}
      >
        {isSubmitting ? "Creating..." : "Create"}
      </Button>
    </div>
  )
}
