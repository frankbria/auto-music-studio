"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import {
  fetchTrainingStatus,
  isSettled,
  VoiceModelError,
  type VoiceTrainingStatus,
} from "@/lib/voice-models"

const POLL_INTERVAL_MS = 3000

// Cap polling so a vanished job surfaces an error instead of spinning forever.
// 1200 x 3s = 60 min; the backend abandons a run at 3600s, so this outlasts it.
// ponytail: fixed cap, raise alongside the worker's poll timeout if that grows.
const MAX_POLLS = 1200

export type VoiceTrainingState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "polling"; status: VoiceTrainingStatus }
  | { phase: "settled"; status: VoiceTrainingStatus }
  | { phase: "error"; message: string }

/**
 * Follows one voice-training run to completion (US-25.2).
 *
 * **Progress lives on the server, not in this hook.** That is what makes AC 4 —
 * "returning to the page after navigation restores the current progress state" —
 * fall out for free: the hook re-reads the status on mount rather than keeping a
 * client-side tally that a refresh would destroy. The obvious wrong
 * implementation is a local counter, which is exactly what that criterion exists
 * to catch, so there is a test that remounts and asserts the state comes back.
 *
 * The access token is kept in a ref because it rotates mid-session (#285), so the
 * poll loop always uses the latest without re-subscribing and restarting.
 */
export function useVoiceTraining(
  jobId: string | null,
  { onSettled }: { onSettled?: (status: VoiceTrainingStatus) => void } = {}
): { state: VoiceTrainingState; refresh: () => void } {
  const { accessToken } = useAuth()
  // Initialised from jobId rather than reset inside the effect:
  // react-hooks/set-state-in-effect is an error here, and a synchronous reset in
  // the effect body is exactly what it forbids.
  const [state, setState] = useState<VoiceTrainingState>(
    jobId ? { phase: "loading" } : { phase: "idle" }
  )

  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  const onSettledRef = useRef(onSettled)
  useEffect(() => {
    onSettledRef.current = onSettled
  }, [onSettled])

  // Bumped to force a re-read; the effect below depends on it.
  const [nonce, setNonce] = useState(0)
  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (!jobId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let polls = 0

    const tick = async () => {
      // The reset lives here rather than in the effect body: switching jobs must
      // not leave the previous run's progress on screen, and setState inside the
      // async callback is what the lint rule allows.
      if (polls === 0 && !cancelled) setState({ phase: "loading" })

      const token = tokenRef.current
      if (!token) {
        // No token yet (auth still settling); wait rather than failing outright.
        timer = setTimeout(tick, POLL_INTERVAL_MS)
        return
      }

      try {
        const status = await fetchTrainingStatus(jobId, token)
        if (cancelled) return

        if (isSettled(status.status)) {
          setState({ phase: "settled", status })
          onSettledRef.current?.(status)
          return
        }

        setState({ phase: "polling", status })
      } catch (error) {
        if (cancelled) return
        const message =
          error instanceof VoiceModelError
            ? error.message
            : "Could not load training progress."
        setState({ phase: "error", message })
        return
      }

      polls += 1
      if (polls >= MAX_POLLS) {
        setState({
          phase: "error",
          message: "Training is taking longer than expected. Check back later.",
        })
        return
      }

      timer = setTimeout(tick, POLL_INTERVAL_MS)
    }

    void tick()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId, nonce])

  return { state, refresh }
}
