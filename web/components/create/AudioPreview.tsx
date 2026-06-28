"use client"

import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"

/**
 * Preview an attached audio source in the Upload/Record tabs (US-16.8). Uses the
 * native <audio controls> element (play/pause/scrub/duration come for free) and,
 * for File/Blob sources, an object URL set straight onto the element via a ref
 * (no component state) and revoked on change/unmount. An optional Clear button
 * lets the user re-upload or re-record.
 */
export function AudioPreview({
  source,
  label,
  onClear,
}: {
  source: File | Blob | string
  label?: string
  onClear?: () => void
}) {
  const audioRef = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    if (typeof source === "string") {
      el.src = source
      return
    }
    const objectUrl = URL.createObjectURL(source)
    el.src = objectUrl
    return () => URL.revokeObjectURL(objectUrl)
  }, [source])

  return (
    <div className="flex flex-col gap-2">
      {label && (
        <span className="truncate text-sm font-medium" title={label}>
          {label}
        </span>
      )}
      <audio
        ref={audioRef}
        controls
        aria-label={label ? `Preview ${label}` : "Audio preview"}
        className="w-full"
      />
      {onClear && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-fit"
          onClick={onClear}
        >
          Clear
        </Button>
      )}
    </div>
  )
}
