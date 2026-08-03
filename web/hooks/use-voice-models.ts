"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import {
  deleteVoiceModel,
  fetchVoiceModels,
  updateVoiceModel,
  VoiceModelError,
  type VoiceModelSummary,
} from "@/lib/voice-models"

export type VoiceModelsState =
  | { phase: "loading" }
  | { phase: "ready"; models: VoiceModelSummary[] }
  /** No access token: signed out, or a refresh that failed. Distinct from an
      error so the UI can say "sign in" rather than showing a red failure. */
  | { phase: "signed-out" }
  | { phase: "error"; message: string }

export type UseVoiceModels = {
  state: VoiceModelsState
  /** Re-read the library from the server. */
  refresh: () => void
  /** Rename and/or re-describe. Rejects with the server's message. */
  rename: (id: string, update: { name?: string; description?: string }) => Promise<void>
  /** Delete and free the stored weights. Rejects with the server's message. */
  remove: (id: string) => Promise<void>
}

/**
 * The caller's voice model library (US-25.3).
 *
 * Mutations re-read from the server rather than patching local state: the list is
 * the server's, and a rename that only updated a local copy would drift the moment
 * anything else changed the row. The access token is kept in a ref because it
 * rotates mid-session (#285).
 */
export function useVoiceModels(): UseVoiceModels {
  const { accessToken } = useAuth()
  const [state, setState] = useState<VoiceModelsState>({ phase: "loading" })
  const [nonce, setNonce] = useState(0)

  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      const token = tokenRef.current

      if (!token) {
        // Drops the models as well as stopping the spinner. Without this a
        // cleared token leaves the previous user's voice metadata on screen
        // until navigation completes, and a first visit spins forever.
        if (!cancelled) setState({ phase: "signed-out" })
        return
      }

      try {
        const models = await fetchVoiceModels(token)
        if (!cancelled) setState({ phase: "ready", models })
      } catch (error) {
        if (cancelled) return
        setState({
          phase: "error",
          message:
            error instanceof VoiceModelError ? error.message : "Could not load your voice models.",
        })
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [nonce, accessToken])

  const rename = useCallback(
    async (id: string, update: { name?: string; description?: string }) => {
      const token = tokenRef.current
      if (!token) throw new VoiceModelError("Not signed in.", 401)
      await updateVoiceModel(id, token, update)
      refresh()
    },
    [refresh]
  )

  const remove = useCallback(
    async (id: string) => {
      const token = tokenRef.current
      if (!token) throw new VoiceModelError("Not signed in.", 401)
      await deleteVoiceModel(id, token)
      refresh()
    },
    [refresh]
  )

  return { state, refresh, rename, remove }
}
