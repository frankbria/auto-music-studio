"use client"

import { useId } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatMs, parseTimeString } from "@/lib/editing-validation"

// Labelled time-string input for the editing modals (US-17.3). Accepts the
// backend's human formats ("30s", "1m30s", "1.5s", "5") and shows a live parsed
// preview so the user sees what a value resolves to. An externally-supplied
// `error` (from the modal's validator) renders inline; otherwise a non-empty,
// unparseable value shows a gentle format hint.

export function TimeDurationInput({
  label,
  value,
  onChange,
  placeholder = "30s",
  error,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  error?: string | null
}) {
  const id = useId()
  const parsedMs = value.trim() ? parseTimeString(value) : null
  const unparseable = value.trim() !== "" && parsedMs === null
  const showError = error || (unparseable ? 'Use a time like "30s" or "1m30s".' : null)

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>{label}</Label>
        {parsedMs !== null && (
          <span className="text-xs text-muted-foreground">= {formatMs(parsedMs)}</span>
        )}
      </div>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        inputMode="text"
        aria-invalid={Boolean(showError)}
      />
      {showError && <p className="text-xs text-destructive">{showError}</p>}
    </div>
  )
}
