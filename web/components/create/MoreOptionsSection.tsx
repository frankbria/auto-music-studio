"use client"

import { useId, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, ArrowRight01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { SELECT_CLASS } from "@/lib/constants/ui"
import {
  BPM_MAX,
  BPM_MIN,
  DURATION_MAX,
  DURATION_MIN,
  DURATION_PRESETS,
  KEY_OPTIONS,
  STYLE_INFLUENCE_MAX,
  STYLE_INFLUENCE_MIN,
  VALID_TIME_SIGNATURES,
  WEIRDNESS_MAX,
  WEIRDNESS_MIN,
} from "@/lib/constants/generation"

/** The generation parameters owned by the collapsible "More Options" section. */
export type MoreOptions = {
  bpmAuto: boolean
  bpm: string
  duration: string
  weirdness: number
  styleInfluence: number
  seedRandom: boolean
  seed: string
  key: string
  timeSignature: string
  /** UI-only — not sent to the API. */
  vocalGender: "male" | "female"
  /** UI-only — not sent to the API. */
  excludeStyles: string
  /** UI-only — reserved for post-generation clip rename. */
  songTitle: string
}

/**
 * A labelled control row. When `htmlFor` is given the visible label is a real
 * `<label>` so clicking it (and voice-control "click X") focuses the input;
 * fields with multiple/zero focusable controls (sliders, the gender toggle) omit
 * it and rely on each control's own `aria-label`.
 */
function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
        </label>
      ) : (
        <span className="text-sm font-medium">{label}</span>
      )}
      {children}
    </div>
  )
}

/**
 * The collapsible "More Options" section (US-16.2): every remaining generation
 * parameter from spec section 4.4. Collapsed by default. Uses native `<select>`
 * and range inputs (accessible, no extra dependencies). UI-only fields (vocal
 * gender, exclude styles, song title) are held for completeness but never sent.
 */
export function MoreOptionsSection({
  value,
  onChange,
}: {
  value: MoreOptions
  onChange: (patch: Partial<MoreOptions>) => void
}) {
  const [open, setOpen] = useState(false)
  const base = useId()
  const id = (name: string) => `${base}-${name}`
  const panelId = id("panel")

  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-fit items-center gap-1.5 text-sm font-medium"
      >
        <HugeiconsIcon icon={open ? ArrowDown01Icon : ArrowRight01Icon} className="size-4" />
        More Options
      </button>

      {/* Always rendered (hidden when collapsed) so aria-controls always resolves. */}
      <div id={panelId} hidden={!open} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="BPM" htmlFor={id("bpm")}>
          <div className="flex items-center gap-2">
            <Input
              id={id("bpm")}
              type="number"
              min={BPM_MIN}
              max={BPM_MAX}
              disabled={value.bpmAuto}
              value={value.bpm}
              onChange={(e) => onChange({ bpm: e.target.value })}
            />
            <div className="flex shrink-0 items-center gap-1.5">
              <Switch
                id={id("bpm-auto")}
                checked={value.bpmAuto}
                onCheckedChange={(c) => onChange({ bpmAuto: c })}
              />
              <Label htmlFor={id("bpm-auto")}>Auto</Label>
            </div>
          </div>
        </Field>

        <Field label="Duration (seconds)" htmlFor={id("duration")}>
          <div className="flex flex-col gap-1.5">
            <Input
              id={id("duration")}
              type="number"
              min={DURATION_MIN}
              max={DURATION_MAX}
              placeholder="Auto"
              value={value.duration}
              onChange={(e) => onChange({ duration: e.target.value })}
            />
            <div className="flex flex-wrap gap-1.5">
              {DURATION_PRESETS.map((preset) => (
                <Button
                  key={preset}
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={() => onChange({ duration: String(preset) })}
                >
                  {preset}s
                </Button>
              ))}
            </div>
          </div>
        </Field>

        <Field label={`Weirdness: ${value.weirdness}`}>
          <input
            type="range"
            min={WEIRDNESS_MIN}
            max={WEIRDNESS_MAX}
            aria-label={`Weirdness: ${value.weirdness}`}
            value={value.weirdness}
            onChange={(e) => onChange({ weirdness: Number(e.target.value) })}
            className="w-full"
          />
        </Field>

        <Field label={`Style influence: ${value.styleInfluence}`}>
          <input
            type="range"
            min={STYLE_INFLUENCE_MIN}
            max={STYLE_INFLUENCE_MAX}
            aria-label={`Style influence: ${value.styleInfluence}`}
            value={value.styleInfluence}
            onChange={(e) => onChange({ styleInfluence: Number(e.target.value) })}
            className="w-full"
          />
        </Field>

        <Field label="Key" htmlFor={id("key")}>
          <select
            id={id("key")}
            className={SELECT_CLASS}
            value={value.key}
            onChange={(e) => onChange({ key: e.target.value })}
          >
            <option value="">Any</option>
            {KEY_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Time signature" htmlFor={id("time-signature")}>
          <select
            id={id("time-signature")}
            className={SELECT_CLASS}
            value={value.timeSignature}
            onChange={(e) => onChange({ timeSignature: e.target.value })}
          >
            <option value="">Any</option>
            {VALID_TIME_SIGNATURES.map((ts) => (
              <option key={ts} value={ts}>
                {ts}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Vocal gender">
          <div className="flex gap-1.5">
            {(["female", "male"] as const).map((gender) => (
              <Button
                key={gender}
                type="button"
                size="sm"
                variant={value.vocalGender === gender ? "default" : "outline"}
                aria-pressed={value.vocalGender === gender}
                className="capitalize"
                onClick={() => onChange({ vocalGender: gender })}
              >
                {gender}
              </Button>
            ))}
          </div>
        </Field>

        <Field label="Seed" htmlFor={id("seed")}>
          <div className="flex items-center gap-2">
            <Input
              id={id("seed")}
              type="number"
              placeholder="Random"
              disabled={value.seedRandom}
              value={value.seed}
              onChange={(e) => onChange({ seed: e.target.value })}
            />
            <div className="flex shrink-0 items-center gap-1.5">
              <Switch
                id={id("seed-random")}
                checked={value.seedRandom}
                onCheckedChange={(c) => onChange({ seedRandom: c })}
              />
              <Label htmlFor={id("seed-random")}>Random</Label>
            </div>
          </div>
        </Field>

        <Field label="Exclude styles" htmlFor={id("exclude")}>
          <Input
            id={id("exclude")}
            placeholder="Styles to avoid"
            value={value.excludeStyles}
            onChange={(e) => onChange({ excludeStyles: e.target.value })}
          />
        </Field>

        <Field label="Song title" htmlFor={id("title")}>
          <Input
            id={id("title")}
            placeholder="Untitled"
            value={value.songTitle}
            onChange={(e) => onChange({ songTitle: e.target.value })}
          />
        </Field>

        {/* No frontend proxy for GET /api/v1/workspaces yet (US-16.2 stub). */}
        <Field label="Save to workspace" htmlFor={id("workspace")}>
          <select id={id("workspace")} className={cn(SELECT_CLASS, "opacity-50")} disabled>
            <option>Coming soon</option>
          </select>
        </Field>
      </div>
    </div>
  )
}
