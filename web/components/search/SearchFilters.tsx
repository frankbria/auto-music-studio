"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { versionLabel } from "@/lib/clip-labels"
import { GENRES } from "@/lib/explore"
import { type SearchParams } from "@/lib/search"
import { cn } from "@/lib/utils"

// Filter panel for the Search page (US-20.2). Prop-driven (no URL/router access)
// so it renders in tests directly. Genre, BPM range, key, and model narrow the
// mock discovery pool client-side; Duration and Creation Date are shown disabled
// because no backend contract for them exists yet (CodeRabbit design choice 2).

type Patch = Partial<SearchParams>

/** A single-select "Any / value…" dropdown built on the radio primitive. */
function FilterSelect({
  label,
  value,
  options,
  optionLabel = (v) => v,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  optionLabel?: (value: string) => string
  onChange: (value: string) => void
}) {
  const ANY = "__any__"
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="justify-between gap-1">
            <span className="truncate">{value ? optionLabel(value) : "Any"}</span>
            <HugeiconsIcon icon={ArrowDown01Icon} size={14} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
          <DropdownMenuRadioGroup
            value={value || ANY}
            onValueChange={(v) => onChange(v === ANY ? "" : v)}
          >
            <DropdownMenuRadioItem value={ANY}>Any</DropdownMenuRadioItem>
            {options.map((opt) => (
              <DropdownMenuRadioItem key={opt} value={opt}>
                {optionLabel(opt)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** Read-only placeholder for a filter whose backend support hasn't landed. */
function ComingSoonFilter({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-1.5 opacity-50">
      <Label>{label}</Label>
      <div
        aria-disabled
        className="flex h-8 items-center rounded-md border border-dashed border-border px-3 text-xs text-muted-foreground"
      >
        Coming soon
      </div>
    </div>
  )
}

export function SearchFilters({
  params,
  onChange,
  keys,
  models,
}: {
  params: SearchParams
  onChange: (patch: Patch) => void
  keys: string[]
  models: string[]
}) {
  const hasActiveFilter =
    !!params.style ||
    params.bpmMin != null ||
    params.bpmMax != null ||
    !!params.key ||
    !!params.model

  const bpm = (raw: string): number | null => {
    const n = Number.parseInt(raw, 10)
    return Number.isFinite(n) ? n : null
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Filters</h2>
        {hasActiveFilter && (
          <button
            type="button"
            onClick={() =>
              onChange({
                style: "",
                bpmMin: null,
                bpmMax: null,
                key: "",
                model: "",
              })
            }
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Genre — single-select chips; clicking the active chip clears it. */}
      <div className="flex flex-col gap-1.5">
        <Label>Genre</Label>
        <div className="flex flex-wrap gap-1.5">
          {GENRES.map((g) => {
            const active = params.style === g.slug
            return (
              <button
                key={g.id}
                type="button"
                aria-pressed={active}
                onClick={() => onChange({ style: active ? "" : g.slug })}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border hover:bg-accent"
                )}
              >
                {g.name}
              </button>
            )
          })}
        </div>
      </div>

      {/* BPM range — two number inputs (the slider primitive is single-thumb). */}
      <div className="flex flex-col gap-1.5">
        <Label>BPM</Label>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            inputMode="numeric"
            min={0}
            value={params.bpmMin ?? ""}
            onChange={(e) => onChange({ bpmMin: bpm(e.target.value) })}
            placeholder="Min"
            aria-label="Minimum BPM"
            className="w-20"
          />
          <span className="text-muted-foreground">–</span>
          <Input
            type="number"
            inputMode="numeric"
            min={0}
            value={params.bpmMax ?? ""}
            onChange={(e) => onChange({ bpmMax: bpm(e.target.value) })}
            placeholder="Max"
            aria-label="Maximum BPM"
            className="w-20"
          />
        </div>
      </div>

      <FilterSelect
        label="Key"
        value={params.key}
        options={keys}
        onChange={(key) => onChange({ key })}
      />
      <FilterSelect
        label="Model"
        value={params.model}
        options={models}
        optionLabel={(m) => versionLabel(m) ?? m}
        onChange={(model) => onChange({ model })}
      />

      <ComingSoonFilter label="Duration" />
      <ComingSoonFilter label="Created" />
    </div>
  )
}
