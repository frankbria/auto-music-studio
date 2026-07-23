"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  CUSTOM_LUFS_MAX,
  CUSTOM_LUFS_MIN,
  MASTERING_PROFILES,
  MASTERING_SERVICES,
  type MasteringConfig,
  type MasteringProfile,
  type MasteringService,
} from "@/lib/mastering"

/**
 * Mastering configuration panel (US-21.2): pick a profile (loudness target), a
 * service, and — for the Custom profile — a LUFS target, then start the job.
 *
 * The two selectors are inlined RadioGroups (the codebase has no Select/
 * ToggleGroup primitive, and neither selector has an independent consumer). The
 * Custom profile reveals a LUFS input constrained to the backend's remaster
 * bounds; an out-of-range value keeps Start disabled so a bad value never 422s.
 */
export function MasteringConfig({
  onStart,
  disabled = false,
}: {
  onStart: (config: MasteringConfig) => void
  /** Disable the whole form (e.g. while a job is submitting). */
  disabled?: boolean
}) {
  const [profile, setProfile] = useState<MasteringProfile>("streaming")
  const [service, setService] = useState<MasteringService>("dolby")
  // Raw input string; parsed + range-checked only for the custom profile.
  const [customLufs, setCustomLufs] = useState("-14")

  const customValue = Number(customLufs)
  const customValid =
    customLufs.trim() !== "" &&
    Number.isFinite(customValue) &&
    customValue >= CUSTOM_LUFS_MIN &&
    customValue <= CUSTOM_LUFS_MAX
  const canStart = !disabled && (profile !== "custom" || customValid)

  function handleStart() {
    const config: MasteringConfig = { profile, service, format: "wav" }
    if (profile === "custom") config.target_lufs = customValue
    onStart(config)
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Profile selector */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Mastering profile</legend>
        <RadioGroup
          value={profile}
          onValueChange={(v) => setProfile(v as MasteringProfile)}
          aria-label="Mastering profile"
        >
          {MASTERING_PROFILES.map((p) => (
            <div key={p.value} className="flex items-center gap-2">
              <RadioGroupItem value={p.value} id={`profile-${p.value}`} />
              <Label htmlFor={`profile-${p.value}`} className="font-normal">
                {p.label}
                {p.lufs !== null && (
                  <span className="ml-1 text-muted-foreground tabular-nums">
                    ({p.lufs} LUFS)
                  </span>
                )}
              </Label>
            </div>
          ))}
        </RadioGroup>

        {profile === "custom" && (
          <div className="flex flex-col gap-1 pl-6">
            <Label htmlFor="custom-lufs" className="text-xs text-muted-foreground">
              Target loudness (LUFS)
            </Label>
            <Input
              id="custom-lufs"
              type="number"
              inputMode="numeric"
              min={CUSTOM_LUFS_MIN}
              max={CUSTOM_LUFS_MAX}
              value={customLufs}
              onChange={(e) => setCustomLufs(e.target.value)}
              className="w-32"
              aria-invalid={!customValid}
            />
            {!customValid && (
              <p className="text-xs text-destructive">
                Enter a value between {CUSTOM_LUFS_MIN} and {CUSTOM_LUFS_MAX}.
              </p>
            )}
          </div>
        )}
      </fieldset>

      {/* Service selector */}
      <fieldset className="flex flex-col gap-3" disabled={disabled}>
        <legend className="text-sm font-medium">Mastering service</legend>
        <RadioGroup
          value={service}
          onValueChange={(v) => setService(v as MasteringService)}
          aria-label="Mastering service"
        >
          {MASTERING_SERVICES.map((s) => (
            <div key={s.value} className="flex items-center gap-2">
              <RadioGroupItem value={s.value} id={`service-${s.value}`} />
              <Label htmlFor={`service-${s.value}`} className="font-normal">
                {s.label}
                <span className="ml-1 text-muted-foreground tabular-nums">
                  ({s.cost} credits)
                </span>
              </Label>
            </div>
          ))}
        </RadioGroup>
      </fieldset>

      <div>
        <Button onClick={handleStart} disabled={!canStart}>
          Start Mastering
        </Button>
      </div>
    </div>
  )
}
