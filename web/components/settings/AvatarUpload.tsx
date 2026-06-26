"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { UserIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { FieldError } from "@/components/settings/FieldError"

const ACCEPTED = ["image/jpeg", "image/png", "image/gif", "image/webp"]

/**
 * Avatar picker with drag-and-drop, file selection, and a square local preview.
 * ponytail: preview only — the backend avatar endpoint (US-8.5) doesn't exist
 * yet, so the chosen image is never persisted. The square crop is CSS
 * (object-cover) rather than a crop library; revisit when upload lands.
 */
export function AvatarUpload({ currentUrl }: { currentUrl: string | null }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  // Free the object URL when it's replaced or the component unmounts.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  function selectFile(file: File | undefined) {
    if (!file) return
    if (!ACCEPTED.includes(file.type)) {
      setError("Please choose an image (JPG, PNG, GIF, or WebP).")
      return
    }
    setError(null)
    // The effect below owns revocation: it revokes the prior URL when this
    // value changes and on unmount, so we only create here.
    setPreviewUrl(URL.createObjectURL(file))
  }

  const shown = previewUrl ?? currentUrl

  return (
    <div data-slot="avatar-upload" className="flex flex-col gap-2">
      <div className="flex items-center gap-4">
        <span className="flex size-20 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-muted-foreground">
          {shown ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL / external avatar, no Next loader needed
            <img
              src={shown}
              alt="Avatar preview"
              className="size-full object-cover"
            />
          ) : (
            <HugeiconsIcon icon={UserIcon} size={32} />
          )}
        </span>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            selectFile(e.dataTransfer.files?.[0])
          }}
          className={
            "flex flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted-foreground transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none" +
            (dragging ? " border-ring bg-muted" : "")
          }
        >
          Drag an image here, or click to choose
        </button>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="hidden"
          aria-label="Avatar image"
          onChange={(e) => selectFile(e.target.files?.[0])}
        />
      </div>

      <Badge variant="outline" className="w-fit">
        Avatar upload coming soon
      </Badge>
      <FieldError message={error} />
    </div>
  )
}
