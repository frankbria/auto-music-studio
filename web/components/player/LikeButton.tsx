"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { FavouriteIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { useLikeToggle } from "@/hooks/use-like-toggle"
import { cn } from "@/lib/utils"

/** Heart toggle for the current track; saved on the server when signed in (#656). */
export function LikeButton() {
  const { state } = usePlayer()
  const toggleLike = useLikeToggle()
  const id = state.current?.id
  const liked = id ? state.likedIds.includes(id) : false

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={liked ? "Unlike" : "Like"}
      aria-pressed={liked}
      disabled={!id}
      onClick={() => id && toggleLike(id)}
      className={cn(
        "transition-transform active:scale-125",
        liked && "text-primary"
      )}
    >
      <HugeiconsIcon
        icon={FavouriteIcon}
        size={18}
        className={cn(liked && "fill-current")}
      />
    </Button>
  )
}
