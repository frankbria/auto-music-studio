"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Cancel01Icon, LockIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useSubscriptionTier } from "@/hooks/use-subscription-tier"
import {
  MAX_REFERENCE_IMAGES,
  PROMPT_MAX_LENGTH,
  VIDEO_ASPECT_RATIOS,
  VIDEO_FRAME_RATES,
  VIDEO_RESOLUTIONS,
  VIDEO_STYLE_PRESETS,
  VIDEO_TRANSITIONS,
  estimateVideoCost,
  type VideoAspectRatio,
  type VideoConfig,
  type VideoFrameRate,
  type VideoResolution,
  type VideoStylePreset,
  type VideoTransitions,
} from "@/lib/video"
import type { Clip } from "@/lib/workspace-clips"

/** One locally selected reference image and its preview object URL. */
type ReferenceImage = { file: File; url: string }

/**
 * Video configuration form (US-22.2): style prompt + presets, reference images,
 * lyrics sync, and the aspect/resolution/frame-rate/transitions pickers, with a
 * live credit estimate. Generate stays disabled until a prompt or preset exists
 * (the backend 422s otherwise). Pickers are inlined RadioGroups in fieldsets
 * (mastering-config idiom — the codebase has no Select/ToggleGroup primitive).
 *
 * Pro gating: 1080p/4K are badge-locked and disabled for free users
 * (SongActionsMenu idiom). Reference images are previewed locally but not sent —
 * the backend accepts only hosted http(s) URLs and no image-hosting endpoint
 * exists yet (documented limitation; wiring lands with a Stage 22 follow-up).
 */
export function VideoForm({
  clip,
  onGenerate,
  disabled = false,
}: {
  clip: Clip
  onGenerate: (config: VideoConfig) => void
  /** Disable the whole form (e.g. while a job is submitting). */
  disabled?: boolean
}) {
  const { isFreeTier } = useSubscriptionTier()

  const [prompt, setPrompt] = useState("")
  const [preset, setPreset] = useState<VideoStylePreset | null>(null)
  const [images, setImages] = useState<ReferenceImage[]>([])
  const [imageError, setImageError] = useState<string | null>(null)
  const [lyricsSync, setLyricsSync] = useState(false)
  const [aspectRatio, setAspectRatio] = useState<VideoAspectRatio>("16:9")
  const [resolution, setResolution] = useState<VideoResolution>("720p")
  const [frameRate, setFrameRate] = useState<VideoFrameRate>(30)
  const [transitions, setTransitions] = useState<VideoTransitions>("auto")
  // Bumped to remount the file input so re-selecting the same files re-fires
  // change (DistributionForm cover-art idiom).
  const [imageInputKey, setImageInputKey] = useState(0)

  // Revoke preview URLs on unmount (the form unmounts the moment a job is
  // submitted). A ref — not [images] deps — so the cleanup only fires once, at
  // unmount, and never revokes URLs still on screen.
  const imagesRef = useRef(images)
  useEffect(() => {
    imagesRef.current = images
  }, [images])
  useEffect(() => {
    return () => {
      for (const img of imagesRef.current) URL.revokeObjectURL(img.url)
    }
  }, [])

  const cost = estimateVideoCost(resolution, clip.duration)
  const canGenerate = !disabled && (prompt.trim() !== "" || preset !== null)

  /** Seed the prompt with the preset's text (US-22.2 acceptance criterion). */
  function selectPreset(next: VideoStylePreset) {
    setPreset(next)
    const text = VIDEO_STYLE_PRESETS.find((p) => p.value === next)?.prompt
    if (text) setPrompt(text)
  }

  function handleImages(files: FileList | null) {
    setImageInputKey((k) => k + 1)
    if (!files || files.length === 0) return
    const added = Array.from(files)
    if (added.some((f) => !f.type.startsWith("image/"))) {
      setImageError("Image files only (JPG, PNG, …).")
      return
    }
    if (images.length + added.length > MAX_REFERENCE_IMAGES) {
      setImageError(`Add up to ${MAX_REFERENCE_IMAGES} reference images.`)
      return
    }
    setImageError(null)
    setImages((prev) => [
      ...prev,
      ...added.map((file) => ({ file, url: URL.createObjectURL(file) })),
    ])
  }

  function removeImage(url: string) {
    URL.revokeObjectURL(url)
    setImages((prev) => prev.filter((img) => img.url !== url))
    setImageError(null)
  }

  function handleGenerate() {
    const config: VideoConfig = {
      lyrics_sync: lyricsSync,
      aspect_ratio: aspectRatio,
      resolution,
      frame_rate: frameRate,
      transitions,
    }
    if (prompt.trim()) config.prompt = prompt.trim()
    if (preset) config.style_preset = preset
    onGenerate(config)
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Style presets — chips that seed the prompt below. */}
      <div role="group" aria-label="Style preset" className="flex flex-col gap-2">
        <span className="text-sm font-medium">Style preset</span>
        <div className="flex flex-wrap gap-2">
          {VIDEO_STYLE_PRESETS.map((p) => (
            <Button
              key={p.value}
              type="button"
              size="sm"
              variant={preset === p.value ? "default" : "outline"}
              disabled={disabled}
              aria-pressed={preset === p.value}
              onClick={() => selectPreset(p.value)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Free-form style prompt. */}
      <div className="flex flex-col gap-2">
        <Label htmlFor="video-prompt">Style prompt</Label>
        <Textarea
          id="video-prompt"
          value={prompt}
          maxLength={PROMPT_MAX_LENGTH}
          disabled={disabled}
          placeholder="Describe the visual aesthetic for your video…"
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>

      {/* Reference images — local previews only (no hosting endpoint yet). */}
      <div className="flex flex-col gap-2">
        <Label htmlFor="video-reference-images">
          Reference images{" "}
          <span className="font-normal text-muted-foreground">
            (up to {MAX_REFERENCE_IMAGES}, optional)
          </span>
        </Label>
        <input
          key={imageInputKey}
          id="video-reference-images"
          type="file"
          accept="image/*"
          multiple
          disabled={disabled}
          className="text-sm"
          aria-invalid={imageError !== null}
          aria-describedby={imageError ? "video-reference-error" : undefined}
          onChange={(e) => handleImages(e.target.files)}
        />
        {imageError && (
          <p id="video-reference-error" className="text-sm text-destructive">
            {imageError}
          </p>
        )}
        {images.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {images.map((img) => (
              <li key={img.url} className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element -- local
                    object URL previews; next/image can't optimize blobs. */}
                <img
                  src={img.url}
                  alt={`Reference ${img.file.name}`}
                  className="size-16 rounded-md object-cover"
                />
                <Button
                  type="button"
                  size="icon"
                  variant="secondary"
                  className="absolute -right-2 -top-2 size-5"
                  aria-label={`Remove ${img.file.name}`}
                  disabled={disabled}
                  onClick={() => removeImage(img.url)}
                >
                  <HugeiconsIcon icon={Cancel01Icon} size={12} />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Lyrics sync. */}
      <div className="flex items-center gap-3">
        <Switch
          id="video-lyrics-sync"
          checked={lyricsSync}
          disabled={disabled}
          onCheckedChange={setLyricsSync}
        />
        <Label htmlFor="video-lyrics-sync">Lyrics sync</Label>
        <span className="text-xs text-muted-foreground">
          Animated lyric overlays synced to the audio
        </span>
      </div>

      {/* Aspect ratio. */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Aspect ratio</legend>
        <RadioGroup
          value={aspectRatio}
          onValueChange={(v) => setAspectRatio(v as VideoAspectRatio)}
          aria-label="Aspect ratio"
          className="flex flex-wrap gap-4"
        >
          {VIDEO_ASPECT_RATIOS.map((a) => (
            <div key={a.value} className="flex items-center gap-2">
              <RadioGroupItem value={a.value} id={`aspect-${a.value}`} />
              <Label htmlFor={`aspect-${a.value}`} className="font-normal">
                {a.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </fieldset>

      {/* Resolution — 1080p/4K are Pro-gated. */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Resolution</legend>
        <RadioGroup
          value={resolution}
          onValueChange={(v) => setResolution(v as VideoResolution)}
          aria-label="Resolution"
          className="flex flex-wrap gap-4"
        >
          {VIDEO_RESOLUTIONS.map((r) => {
            const locked = r.proOnly && isFreeTier
            return (
              <div key={r.value} className="flex items-center gap-2">
                <RadioGroupItem
                  value={r.value}
                  id={`resolution-${r.value}`}
                  disabled={locked}
                />
                <Label
                  htmlFor={`resolution-${r.value}`}
                  className="flex items-center gap-1 font-normal"
                >
                  {r.label}
                  {r.proOnly && (
                    <Badge variant="outline" className="text-[10px]">
                      {locked && (
                        <HugeiconsIcon icon={LockIcon} data-icon="inline-start" />
                      )}
                      Pro
                    </Badge>
                  )}
                </Label>
              </div>
            )
          })}
        </RadioGroup>
        {isFreeTier && (
          <p className="text-xs text-muted-foreground">
            1080p and 4K rendering are Pro features. Upgrade to Pro to unlock
            higher resolutions.
          </p>
        )}
      </fieldset>

      {/* Frame rate. */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Frame rate</legend>
        <RadioGroup
          value={String(frameRate)}
          onValueChange={(v) => setFrameRate(Number(v) as VideoFrameRate)}
          aria-label="Frame rate"
          className="flex flex-wrap gap-4"
        >
          {VIDEO_FRAME_RATES.map((f) => (
            <div key={f.value} className="flex items-center gap-2">
              <RadioGroupItem value={String(f.value)} id={`fps-${f.value}`} />
              <Label htmlFor={`fps-${f.value}`} className="font-normal">
                {f.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </fieldset>

      {/* Scene transitions. */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Scene transitions</legend>
        <RadioGroup
          value={transitions}
          onValueChange={(v) => setTransitions(v as VideoTransitions)}
          aria-label="Scene transitions"
          className="flex flex-wrap gap-4"
        >
          {VIDEO_TRANSITIONS.map((t) => (
            <div key={t.value} className="flex items-center gap-2">
              <RadioGroupItem value={t.value} id={`transition-${t.value}`} />
              <Label htmlFor={`transition-${t.value}`} className="font-normal">
                {t.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </fieldset>

      {/* Estimate + submit. */}
      <div className="flex items-center gap-4">
        <Button onClick={handleGenerate} disabled={!canGenerate}>
          Generate Video
        </Button>
        <span className="text-sm text-muted-foreground tabular-nums">
          Estimated cost: {cost} credits
        </span>
      </div>
    </div>
  )
}
