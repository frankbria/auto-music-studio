"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Cancel01Icon,
  DragDropVerticalIcon,
  PlayListIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { LAYOUT } from "@/lib/constants/layout"
import { cn } from "@/lib/utils"

/** Toggle button with a badge for the upcoming-track count. */
export function QueueButton() {
  const { state, dispatch } = usePlayer()
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Queue"
      aria-pressed={state.isQueueOpen}
      onClick={() => dispatch({ type: "queue/panel" })}
      className="relative"
    >
      <HugeiconsIcon icon={PlayListIcon} size={18} />
      {state.queue.length > 0 && (
        <span className="absolute -top-0.5 -right-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
          {state.queue.length}
        </span>
      )}
    </Button>
  )
}

/** Slide-up queue panel: current track + reorderable, removable upcoming list. */
export function QueuePanel() {
  const { state, dispatch } = usePlayer()
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  if (!state.isQueueOpen) return null

  function onDrop(to: number) {
    if (dragIndex !== null && dragIndex !== to) {
      dispatch({ type: "queue/reorder", from: dragIndex, to })
    }
    setDragIndex(null)
  }

  return (
    <aside
      aria-label="Play queue"
      style={{ bottom: LAYOUT.playbarHeight }}
      // z-40: above page content, below the z-50 playbar.
      className="fixed right-4 z-40 flex max-h-[60vh] w-80 flex-col overflow-hidden rounded-t-xl border border-border bg-background shadow-lg"
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Queue</h2>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Close queue"
          onClick={() => dispatch({ type: "queue/panel", open: false })}
        >
          <HugeiconsIcon icon={Cancel01Icon} size={16} />
        </Button>
      </header>

      <div className="overflow-y-auto">
        {state.current && (
          <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-2">
            <span className="text-xs font-medium text-primary">
              Now playing
            </span>
            <span className="truncate text-sm">{state.current.title}</span>
          </div>
        )}

        {state.queue.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            Queue is empty.
          </p>
        ) : (
          <ul>
            {state.queue.map((track, i) => (
              <li
                key={`${track.id}-${i}`}
                draggable
                onDragStart={() => setDragIndex(i)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => onDrop(i)}
                className={cn(
                  "group flex items-center gap-2 px-3 py-2 hover:bg-muted/60",
                  dragIndex === i && "opacity-50"
                )}
              >
                <span className="cursor-grab text-muted-foreground" aria-hidden>
                  <HugeiconsIcon icon={DragDropVerticalIcon} size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{track.title}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {track.artist}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${track.title} from queue`}
                  onClick={() => dispatch({ type: "queue/remove", index: i })}
                >
                  <HugeiconsIcon icon={Cancel01Icon} size={14} />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
