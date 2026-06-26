"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  RepeatIcon,
  RepeatOneIcon,
  ShuffleIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { cn } from "@/lib/utils"

/** Repeat (off → all → one) and shuffle toggles. Active state uses the accent. */
export function ModeToggles() {
  const { state, dispatch } = usePlayer()

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Repeat: ${state.repeatMode}`}
        aria-pressed={state.repeatMode !== "off"}
        onClick={() => dispatch({ type: "repeat/cycle" })}
        className={cn(state.repeatMode !== "off" && "text-primary")}
      >
        <HugeiconsIcon
          icon={state.repeatMode === "one" ? RepeatOneIcon : RepeatIcon}
          size={18}
        />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Shuffle"
        aria-pressed={state.shuffle}
        onClick={() => dispatch({ type: "shuffle/toggle" })}
        className={cn(state.shuffle && "text-primary")}
      >
        <HugeiconsIcon icon={ShuffleIcon} size={18} />
      </Button>
    </div>
  )
}
