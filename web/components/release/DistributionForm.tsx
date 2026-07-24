"use client"

import { cloneElement, useEffect, useRef, useState, type ReactElement } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  clearDraft,
  coverArtResolutionError,
  generateIsrc,
  generateUpc,
  loadDraft,
  MIN_COVER_ART_PX,
  prefillFromClip,
  REQUIRED_FIELDS,
  saveDraft,
  validateMetadata,
  type ReleaseCredits,
  type ReleaseMetadata,
} from "@/lib/release-draft"
import type { Clip } from "@/lib/workspace-clips"

/**
 * Distribution metadata form (US-21.4). Pre-populates from the selected song,
 * lets the user review/edit every field, pick or upload cover art (enforcing the
 * store 3000×3000 minimum), enter or auto-generate ISRC/UPC codes, and save an
 * incremental draft. All web-only for now — see [[us-21-4-distribution-metadata-form]]
 * and lib/release-draft.ts for the persistence seam that will become a backend PATCH.
 *
 * A draft is intentionally saveable while incomplete: Save Draft always persists
 * and *also* reveals the required-field validation so the user sees what still
 * needs finishing before distribution (US-21.5).
 */
export function DistributionForm({ clip }: { clip: Clip | null }) {
  if (!clip) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a song above to prepare its release metadata.
      </p>
    )
  }
  return <DistributionFormFields clip={clip} />
}

/** Resume a saved draft merged over a fresh prefill (AC1/AC6). Merging backfills
 *  any fields a draft written by an older version is missing — including the
 *  nested `credits` object — so an old draft can never crash on read.
 *
 *  Reads localStorage during render (here and in the render-phase reset). That's
 *  intentional and the pattern the repo's `set-state-in-effect` lint steers you
 *  toward (derive during render, don't hydrate in an effect). It's safe because
 *  this form only ever mounts client-side: `/release` gates it behind
 *  `useRequireAuth` (renders null until auth resolves on the client) inside a
 *  `useSearchParams` Suspense boundary (renders null on the server), so there is
 *  no server render to diverge from. Mount it elsewhere and it must stay
 *  client-only, or the localStorage read would cause a hydration mismatch. */
function initialMetadata(clip: Clip): ReleaseMetadata {
  const base = prefillFromClip(clip)
  const draft = loadDraft(clip.id)
  if (!draft) return base
  return {
    ...base,
    ...draft,
    credits: { ...base.credits, ...draft.credits },
    coverArt: draft.coverArt ?? base.coverArt,
  }
}

function DistributionFormFields({ clip }: { clip: Clip }) {
  const [metadata, setMetadata] = useState<ReleaseMetadata>(() => initialMetadata(clip))
  // Render-phase reset when the selected song changes — the form re-prefills from
  // the new clip (or its draft) without a setState-in-effect the lint forbids.
  const [prevClipId, setPrevClipId] = useState(clip.id)
  const [showValidation, setShowValidation] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [coverError, setCoverError] = useState<string | null>(null)
  // Bumped to remount the file input so its displayed filename clears on reset.
  const [coverInputKey, setCoverInputKey] = useState(0)
  if (clip.id !== prevClipId) {
    // Auto-persist the outgoing song's edits before switching so unsaved work
    // isn't silently lost — drafts are cheap, keyed per clip, and resumable.
    // ponytail: best-effort save on switch, not a dirty-state confirmation.
    saveDraft(prevClipId, metadata)
    setPrevClipId(clip.id)
    setMetadata(initialMetadata(clip))
    setShowValidation(false)
    setSaved(false)
    setSaveError(null)
    setCoverError(null)
  }

  const errors = validateMetadata(metadata)
  const requiredMissing = REQUIRED_FIELDS.filter(({ key }) => errors[key]).length

  // Persist the current edits on unmount so leaving the Distribute tab (Radix
  // unmounts the inactive panel) or the page doesn't silently drop unsaved work —
  // the draft is picked back up on return. A ref holds the latest values so the
  // cleanup, which runs once, saves what's on screen at that moment. The cleanup
  // calls saveDraft (never setState), so it's clear of the set-state-in-effect lint.
  const latest = useRef({ clipId: clip.id, metadata })
  // Keep the ref current in the commit phase (writing it during render is a lint
  // error) so the unmount cleanup below saves what was last on screen.
  useEffect(() => {
    latest.current = { clipId: clip.id, metadata }
  })
  useEffect(() => {
    const ref = latest
    return () => {
      saveDraft(ref.current.clipId, ref.current.metadata)
    }
  }, [])

  function set<K extends keyof ReleaseMetadata>(key: K, value: ReleaseMetadata[K]) {
    setMetadata((m) => ({ ...m, [key]: value }))
    setSaved(false)
  }
  function setCredit(key: keyof ReleaseCredits, value: string) {
    setMetadata((m) => ({ ...m, credits: { ...m.credits, [key]: value } }))
    setSaved(false)
  }

  function handleSaveDraft() {
    setShowValidation(true)
    if (saveDraft(clip.id, metadata)) {
      setSaved(true)
      setSaveError(null)
    } else {
      setSaved(false)
      setSaveError("Couldn't save the draft — your browser storage may be full or disabled.")
    }
  }

  function handleClearDraft() {
    clearDraft(clip.id)
    setMetadata(prefillFromClip(clip))
    setShowValidation(false)
    setSaved(false)
    setSaveError(null)
    setCoverError(null)
    setCoverInputKey((k) => k + 1)
  }

  async function handleCoverUpload(file: File | undefined) {
    setCoverError(null)
    if (!file) return
    if (file.type !== "image/jpeg" && file.type !== "image/png") {
      setCoverError("Cover art must be a JPG or PNG image.")
      return
    }
    // Resolution enforcement (AC3): decode the image to read its real pixel size.
    // jsdom has no image decoder, so this path is exercised by the live demo.
    const url = URL.createObjectURL(file)
    try {
      const { width, height } = await readImageSize(url)
      const resErr = coverArtResolutionError(width, height)
      if (resErr) {
        setCoverError(resErr)
        return
      }
      set("coverArt", { kind: "uploaded", name: file.name })
    } catch {
      setCoverError("Couldn't read that image. Try a different file.")
    } finally {
      URL.revokeObjectURL(url)
    }
  }

  const invalid = (key: keyof ReleaseMetadata) => showValidation && !!errors[key]

  return (
    <div className="flex flex-col gap-8">
      {/* Core metadata --------------------------------------------------- */}
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Title" htmlFor="rel-title" error={invalid("title") ? errors.title : undefined} required>
          <Input
            id="rel-title"
            value={metadata.title}
            aria-invalid={invalid("title")}
            onChange={(e) => set("title", e.target.value)}
          />
        </Field>
        <Field label="Artist" htmlFor="rel-artist" error={invalid("artist") ? errors.artist : undefined} required>
          <Input
            id="rel-artist"
            value={metadata.artist}
            aria-invalid={invalid("artist")}
            onChange={(e) => set("artist", e.target.value)}
          />
        </Field>
        <Field label="Album name" htmlFor="rel-album">
          <Input id="rel-album" value={metadata.album} onChange={(e) => set("album", e.target.value)} />
        </Field>
        <Field label="Genre" htmlFor="rel-genre" error={invalid("genre") ? errors.genre : undefined} required>
          <Input
            id="rel-genre"
            value={metadata.genre}
            aria-invalid={invalid("genre")}
            onChange={(e) => set("genre", e.target.value)}
          />
        </Field>
        <Field label="BPM" htmlFor="rel-bpm">
          <Input
            id="rel-bpm"
            type="number"
            inputMode="numeric"
            value={metadata.bpm ?? ""}
            onChange={(e) => {
              const n = Number(e.target.value)
              set("bpm", e.target.value === "" || !Number.isFinite(n) ? null : n)
            }}
          />
        </Field>
        <Field label="Key" htmlFor="rel-key">
          <Input id="rel-key" value={metadata.key} onChange={(e) => set("key", e.target.value)} />
        </Field>
        <Field label="Language" htmlFor="rel-language">
          <Input id="rel-language" value={metadata.language} onChange={(e) => set("language", e.target.value)} />
        </Field>
        <Field label="Release date" htmlFor="rel-date">
          <Input
            id="rel-date"
            type="date"
            value={metadata.releaseDate}
            onChange={(e) => set("releaseDate", e.target.value)}
          />
        </Field>
      </section>

      <Field label="Description" htmlFor="rel-description">
        <Textarea
          id="rel-description"
          value={metadata.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </Field>

      <div className="flex items-center gap-3">
        <Switch
          id="rel-explicit"
          checked={metadata.explicit}
          onCheckedChange={(v) => set("explicit", v)}
        />
        <Label htmlFor="rel-explicit" className="font-normal">
          Explicit content
        </Label>
      </div>

      {/* Cover art ------------------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Cover art</h3>
        <p className="text-xs text-muted-foreground">
          Minimum {MIN_COVER_ART_PX}×{MIN_COVER_ART_PX}px, JPG or PNG.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Field label="Upload cover art" htmlFor="rel-cover-upload">
            <input
              key={coverInputKey}
              id="rel-cover-upload"
              type="file"
              accept="image/jpeg,image/png"
              aria-invalid={!!coverError}
              aria-describedby={coverError ? "rel-cover-error" : undefined}
              className="text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm"
              onChange={(e) => void handleCoverUpload(e.target.files?.[0])}
            />
          </Field>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              set("coverArt", { kind: "existing" })
              setCoverError(null) // clear any prior upload-resolution error
            }}
          >
            Use existing art
          </Button>
          {/* ponytail: AI cover-art generation isn't built yet — link is a stub
              until the generation page exists (spec 42.3 "generate via AI"). */}
          <Button type="button" variant="outline" disabled title="Coming soon">
            Generate with AI
          </Button>
        </div>
        {metadata.coverArt.kind !== "none" && !coverError && (
          <p className="text-xs text-muted-foreground">
            {metadata.coverArt.kind === "uploaded"
              ? `Uploaded: ${metadata.coverArt.name}`
              : "Using the song's existing cover art."}
          </p>
        )}
        {coverError && (
          <p id="rel-cover-error" className="text-sm text-destructive">
            {coverError}
          </p>
        )}
      </section>

      {/* Identifiers ----------------------------------------------------- */}
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="ISRC" htmlFor="rel-isrc" error={invalid("isrc") ? errors.isrc : undefined}>
          <div className="flex gap-2">
            <Input
              id="rel-isrc"
              value={metadata.isrc}
              aria-invalid={invalid("isrc")}
              placeholder="US-AMS-25-00001"
              onChange={(e) => set("isrc", e.target.value.toUpperCase())}
            />
            <Button type="button" variant="outline" onClick={() => set("isrc", generateIsrc())}>
              Generate ISRC
            </Button>
          </div>
        </Field>
        <Field label="UPC / EAN" htmlFor="rel-upc" error={invalid("upc") ? errors.upc : undefined}>
          <div className="flex gap-2">
            <Input
              id="rel-upc"
              value={metadata.upc}
              aria-invalid={invalid("upc")}
              placeholder="12-digit UPC"
              onChange={(e) => set("upc", e.target.value)}
            />
            <Button type="button" variant="outline" onClick={() => set("upc", generateUpc())}>
              Generate UPC
            </Button>
          </div>
        </Field>
      </section>

      {/* Copyright + credits -------------------------------------------- */}
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Copyright notice" htmlFor="rel-copyright">
          <Input
            id="rel-copyright"
            value={metadata.copyright}
            placeholder="© 2026 Your Label"
            onChange={(e) => set("copyright", e.target.value)}
          />
        </Field>
        <Field label="Producer" htmlFor="rel-producer">
          <Input id="rel-producer" value={metadata.credits.producer} onChange={(e) => setCredit("producer", e.target.value)} />
        </Field>
        <Field label="Songwriter" htmlFor="rel-songwriter">
          <Input id="rel-songwriter" value={metadata.credits.songwriter} onChange={(e) => setCredit("songwriter", e.target.value)} />
        </Field>
        <Field label="Performer" htmlFor="rel-performer">
          <Input id="rel-performer" value={metadata.credits.performer} onChange={(e) => setCredit("performer", e.target.value)} />
        </Field>
      </section>

      <Field label="Lyrics" htmlFor="rel-lyrics">
        <Textarea
          id="rel-lyrics"
          value={metadata.lyrics}
          className="min-h-32"
          onChange={(e) => set("lyrics", e.target.value)}
        />
      </Field>

      {/* Validation summary + actions ------------------------------------ */}
      {showValidation && requiredMissing > 0 && (
        <p role="alert" className="text-sm text-destructive">
          {requiredMissing} required field{requiredMissing === 1 ? "" : "s"} still need
          {requiredMissing === 1 ? "s" : ""} attention before distribution.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={handleSaveDraft}>
          Save draft
        </Button>
        <Button type="button" variant="outline" onClick={handleClearDraft}>
          Reset to song defaults
        </Button>
        {saved && <span className="text-sm text-muted-foreground">Draft saved.</span>}
      </div>
      {saveError && (
        <p role="alert" className="text-sm text-destructive">
          {saveError}
        </p>
      )}
    </div>
  )
}

/** Labeled field wrapper: label (with required marker) + control + inline error.
 *  When there's an error, the control is linked to the message via aria-describedby
 *  so screen readers announce it (the control still supplies its own aria-invalid). */
function Field({
  label,
  htmlFor,
  required,
  error,
  children,
}: {
  label: string
  htmlFor: string
  required?: boolean
  error?: string
  children: ReactElement
}) {
  const errorId = `${htmlFor}-error`
  const control = error
    ? cloneElement(children, { "aria-describedby": errorId } as { "aria-describedby": string })
    : children
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-sm">
        {label}
        {required && <span className="ml-0.5 text-destructive">*</span>}
      </Label>
      {control}
      {error && (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

/** Read an image's natural pixel dimensions from an object URL. */
function readImageSize(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => reject(new Error("image load failed"))
    img.src = url
  })
}
