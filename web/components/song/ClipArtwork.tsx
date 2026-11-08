"use client"

import { useState, type ReactNode } from "react"

import { useOnReconnect } from "@/hooks/use-on-reconnect"
import { clipArtworkUrl } from "@/lib/clips"
import { cn } from "@/lib/utils"

/**
 * A clip's cover art, or `fallback` when it has none (#749). The art route 404s for a clip without art, so a
 * failure shows the fallback instead of a broken image. It is remembered per clip, so a different clip tries again,
 * and cleared when the connection comes back, so a transient failure recovers.
 */
export function ClipArtwork({
  clipId,
  fallback,
  className,
}: {
  clipId: string
  fallback: ReactNode
  className?: string
}) {
  const [failedFor, setFailedFor] = useState<string | null>(null)
  useOnReconnect(() => setFailedFor(null))
  if (failedFor === clipId) return <>{fallback}</>
  return (
    // eslint-disable-next-line @next/next/no-img-element -- artwork is a dynamic proxied stream, not a build-time asset
    <img
      src={clipArtworkUrl(clipId)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailedFor(clipId)}
      className={cn("size-full object-cover", className)}
    />
  )
}
