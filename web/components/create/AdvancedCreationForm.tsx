"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowTurnBackwardIcon, MagicWand01Icon, SparklesIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/use-auth"
import { InspirationTags } from "@/components/create/InspirationTags"
import { MoreOptionsSection, type MoreOptions } from "@/components/create/MoreOptionsSection"
import { useUndoableField } from "@/components/create/useUndoableField"
import {
  combineStyles,
  submitAdvancedGeneration,
  validateAdvanced,
  type AdvancedFormData,
} from "@/lib/generate"
import {
  STYLE_INFLUENCE_DEFAULT,
  VOCAL_LANGUAGES,
  WEIRDNESS_DEFAULT,
} from "@/lib/constants/generation"

type Status =
  | { kind: "idle" }
  | { kind: "info"; message: string }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string }

const STUB_NOTICE = "This feature is coming soon."

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

const initialOptions: MoreOptions = {
  bpmAuto: true,
  bpm: "",
  duration: "",
  weirdness: WEIRDNESS_DEFAULT,
  styleInfluence: STYLE_INFLUENCE_DEFAULT,
  seedRandom: true,
  seed: "",
  key: "",
  timeSignature: "",
  vocalGender: "female",
  excludeStyles: "",
  songTitle: "",
}

/**
 * The Advanced creation form (US-16.2): separate Lyrics and Styles panels plus a
 * collapsible More Options section, giving precise control over every generation
 * parameter the backend accepts. Mirrors SimpleCreationForm's controlled-state,
 * BFF-submit pattern; lyrics and styles each get single-step undo.
 */
export function AdvancedCreationForm() {
  const router = useRouter()
  const { accessToken } = useAuth()

  const lyricsField = useUndoableField("")
  const stylesField = useUndoableField("")
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [lyricsMode, setLyricsMode] = useState<"manual" | "auto">("manual")
  const [vocalLanguage, setVocalLanguage] = useState("")
  const [instrumental, setInstrumental] = useState(false)
  const [options, setOptions] = useState<MoreOptions>(initialOptions)
  const [status, setStatus] = useState<Status>({ kind: "idle" })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showEnhance, setShowEnhance] = useState(false)
  const [enhancePrompt, setEnhancePrompt] = useState("")

  const updateOptions = (patch: Partial<MoreOptions>) =>
    setOptions((o) => ({ ...o, ...patch }))

  const effectiveStyle = combineStyles(stylesField.value, selectedTags)
  const effectiveLyrics = lyricsMode === "manual" ? lyricsField.value : ""
  // Enabled the moment there's a style or lyrics to build a prompt from; range
  // validation runs on submit so out-of-range values surface a message.
  const canSubmit = effectiveStyle.trim().length > 0 || effectiveLyrics.trim().length > 0

  function formData(): AdvancedFormData {
    return {
      lyrics: lyricsField.value,
      lyricsMode,
      vocalLanguage,
      styles: stylesField.value,
      selectedTags,
      instrumental,
      bpmAuto: options.bpmAuto,
      bpm: options.bpm,
      key: options.key,
      timeSignature: options.timeSignature,
      duration: options.duration,
      weirdness: options.weirdness,
      styleInfluence: options.styleInfluence,
      seedRandom: options.seedRandom,
      seed: options.seed,
    }
  }

  async function handleCreate() {
    if (!canSubmit || isSubmitting) return
    if (!accessToken) {
      router.push("/login")
      return
    }
    const data = formData()
    const error = validateAdvanced(data)
    if (error) {
      setStatus({ kind: "error", message: error })
      return
    }
    setIsSubmitting(true)
    try {
      const result = await submitAdvancedGeneration(data, accessToken)
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
    <div className="flex max-w-2xl flex-col gap-6">
      {/* Lyrics panel */}
      <section className="flex flex-col gap-3" aria-label="Lyrics panel">
        <div className="flex items-center justify-between">
          <Label htmlFor="adv-lyrics">Lyrics</Label>
          <div className="flex gap-1.5">
            {(["manual", "auto"] as const).map((mode) => (
              <Button
                key={mode}
                type="button"
                size="xs"
                variant={lyricsMode === mode ? "default" : "outline"}
                aria-pressed={lyricsMode === mode}
                className="capitalize"
                onClick={() => setLyricsMode(mode)}
              >
                {mode}
              </Button>
            ))}
          </div>
        </div>
        <Textarea
          id="adv-lyrics"
          rows={6}
          placeholder={"[Verse 1]\nYour lyrics here...\n\n[Chorus]\n..."}
          disabled={lyricsMode === "auto"}
          value={lyricsField.value}
          onChange={(e) => lyricsField.setValue(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Vocal language"
            className={`${selectClass} w-auto`}
            value={vocalLanguage}
            onChange={(e) => setVocalLanguage(e.target.value)}
          >
            <option value="">Auto language</option>
            {VOCAL_LANGUAGES.map((lang) => (
              <option key={lang} value={lang}>
                {lang}
              </option>
            ))}
          </select>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={showEnhance}
            onClick={() => setShowEnhance((v) => !v)}
          >
            <HugeiconsIcon icon={SparklesIcon} data-icon="inline-start" />
            Enhance
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!lyricsField.canUndo}
            onClick={lyricsField.undo}
          >
            <HugeiconsIcon icon={ArrowTurnBackwardIcon} data-icon="inline-start" />
            Undo
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => lyricsField.setValue("")}>
            Clear
          </Button>
        </div>
        {showEnhance && (
          <div className="flex items-center gap-2">
            <Input
              aria-label="Enhancement prompt"
              placeholder="Describe how to enhance the lyrics..."
              value={enhancePrompt}
              onChange={(e) => setEnhancePrompt(e.target.value)}
            />
            <Button
              type="button"
              size="sm"
              onClick={() => setStatus({ kind: "info", message: STUB_NOTICE })}
            >
              Apply
            </Button>
          </div>
        )}
      </section>

      {/* Styles panel */}
      <section className="flex flex-col gap-3" aria-label="Styles panel">
        <Label htmlFor="adv-styles">Styles</Label>
        <Textarea
          id="adv-styles"
          rows={2}
          placeholder="Enter styles separated by commas (e.g., cinematic, epic, orchestral)"
          value={stylesField.value}
          onChange={(e) => stylesField.setValue(e.target.value)}
        />
        <InspirationTags
          selectedTags={selectedTags}
          onChange={(next) => setSelectedTags(next)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setStatus({ kind: "info", message: STUB_NOTICE })}
          >
            <HugeiconsIcon icon={MagicWand01Icon} data-icon="inline-start" />
            Magic wand
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!stylesField.canUndo}
            onClick={stylesField.undo}
          >
            <HugeiconsIcon icon={ArrowTurnBackwardIcon} data-icon="inline-start" />
            Undo
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => stylesField.setValue("")}>
            Clear
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <Switch id="adv-instrumental" checked={instrumental} onCheckedChange={setInstrumental} />
            <Label htmlFor="adv-instrumental">Instrumental</Label>
          </div>
        </div>
      </section>

      <MoreOptionsSection value={options} onChange={updateOptions} />

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
