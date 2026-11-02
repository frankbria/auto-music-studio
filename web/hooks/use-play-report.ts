"use client"

import { useCallback, useContext, useEffect, useRef } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { PLAY_THRESHOLD_SECONDS, reportEngagement } from "@/lib/engagement"

/** Longer than any gap between two `timeupdate` events in normal playback, shorter than a deliberate seek. */
const MAX_PLAYBACK_STEP_SECONDS = 2

export type PlayProgress = (clipId: string, currentTime: number) => void

/**
 * Report a play once a clip has been listened to for 30 s (#656). Feed it every `timeupdate`. Only small forward
 * steps count as listening, so a seek or a loop's jump back to 0 adds nothing; switching clips starts the count
 * again. The server counts a listener once an hour, so a replay here costs nothing.
 */
export function usePlayReport(): PlayProgress {
  const token = useContext(AuthContext)?.accessToken ?? null
  const tokenRef = useRef(token)
  useEffect(() => {
    tokenRef.current = token
  }, [token])
  const progress = useRef({ clipId: "", last: 0, listened: 0, reported: false })

  return useCallback((clipId: string, currentTime: number) => {
    const current = progress.current
    if (current.clipId !== clipId) {
      progress.current = {
        clipId,
        last: currentTime,
        listened: 0,
        reported: false,
      }
      return
    }
    const step = currentTime - current.last
    current.last = currentTime
    if (step > 0 && step < MAX_PLAYBACK_STEP_SECONDS) current.listened += step
    if (!current.reported && current.listened >= PLAY_THRESHOLD_SECONDS) {
      current.reported = true
      void reportEngagement(clipId, "play", tokenRef.current)
    }
  }, [])
}
