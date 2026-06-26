"use client"

import { useEffect } from "react"

import {
  usePlayer,
  type PlayerAction,
  type PlayerState,
} from "@/contexts/player-context"

const SEEK_STEP = 5 // seconds
const VOLUME_STEP = 0.1

/** True when focus is in a field where the key should type, not control playback. */
function isEditingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable
  )
}

/**
 * Map a keydown to a player action, or null to ignore it. Pure and exported so
 * the guard + key mapping can be unit-tested without a DOM. `target` is the
 * event target; editing fields are left alone.
 */
export function playerShortcutAction(
  key: string,
  state: PlayerState,
  target: EventTarget | null
): PlayerAction | null {
  if (!state.current) return null
  if (isEditingTarget(target)) return null

  switch (key) {
    case " ":
    case "Spacebar":
      return { type: "toggle" }
    case "ArrowLeft":
      return {
        type: "seek/request",
        time: Math.max(0, state.currentTime - SEEK_STEP),
      }
    case "ArrowRight":
      return {
        type: "seek/request",
        time: Math.min(
          state.duration || Infinity,
          state.currentTime + SEEK_STEP
        ),
      }
    case "ArrowUp":
      return { type: "volume/set", volume: state.volume + VOLUME_STEP }
    case "ArrowDown":
      return { type: "volume/set", volume: state.volume - VOLUME_STEP }
    case "m":
    case "M":
      return { type: "mute/toggle" }
    default:
      return null
  }
}

/** Global keyboard shortcuts for the player; attach once at the shell level. */
export function usePlayerShortcuts(): void {
  const { state, dispatch } = usePlayer()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const action = playerShortcutAction(e.key, state, e.target)
      if (!action) return
      // Space would otherwise scroll the page; arrows are claimed for transport.
      e.preventDefault()
      dispatch(action)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [state, dispatch])
}
