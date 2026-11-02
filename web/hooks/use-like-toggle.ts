"use client"

import { useCallback, useContext } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { usePlayer } from "@/contexts/player-context"
import { saveLike } from "@/lib/engagement"

/**
 * Toggle a clip's like (#656). The heart flips at once; for a signed-in user the like is saved on the server, and a
 * save that fails flips it back. Signed out, the like stays in this browser, as it did before likes were recorded.
 * Reads AuthContext directly, so it works outside an AuthProvider.
 */
export function useLikeToggle(): (clipId: string) => void {
  const { state, dispatch } = usePlayer()
  const token = useContext(AuthContext)?.accessToken ?? null
  const likedIds = state.likedIds

  return useCallback(
    (clipId: string) => {
      const liking = !likedIds.includes(clipId)
      dispatch({ type: "like/toggle", id: clipId })
      if (!token) return
      saveLike(clipId, liking, token).catch(() =>
        dispatch({ type: "like/set", id: clipId, liked: !liking })
      )
    },
    [dispatch, likedIds, token]
  )
}
