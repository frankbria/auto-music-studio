"use client"

import { useId } from "react"

import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { STYLE_MAX_LENGTH } from "@/lib/constants/generation"

// Shared multi-line style/prompt input for the editing modals (US-17.3). A
// labelled textarea with a live character counter capped at the backend's field
// limit (default STYLE_MAX_LENGTH); `maxLength` overrides it for the longer
// prompt/lyrics fields. Optional so it reads as an ordinary form field.

export function StyleTextarea({
  label,
  value,
  onChange,
  placeholder,
  maxLength = STYLE_MAX_LENGTH,
  required = false,
  rows = 3,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  maxLength?: number
  required?: boolean
  rows?: number
}) {
  const id = useId()
  const overLimit = value.length > maxLength

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>
          {label}
          {required && <span className="text-destructive"> *</span>}
        </Label>
        <span
          className={
            overLimit
              ? "text-xs text-destructive"
              : "text-xs text-muted-foreground"
          }
        >
          {value.length}/{maxLength}
        </span>
      </div>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        // Hard-cap input at the backend's field limit so an over-long paste is
        // truncated in the browser instead of surfacing as an avoidable 422.
        maxLength={maxLength}
        aria-invalid={overLimit}
      />
    </div>
  )
}
