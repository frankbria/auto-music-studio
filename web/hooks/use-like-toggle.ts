"use client"

import { useCallback, useContext, useRef } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { usePlayer } from "@/contexts/player-context"
import { LikeSaveError, saveLike } from "@/lib/engagement"

/**
 * Toggle a clip's like (#656). The heart flips at once; for a signed-in user the like is saved on the server, and a
 * save that fails flips it back. A clip outside the public pool (an owner's private clip) answers 404: its like stays
 * in this browser, as every like did before they were recorded. Signed out, likes stay local too. A click on a clip
 * whose save is still in flight is ignored, so a PUT and a DELETE never race and a rollback is always the latest one.
 * Reads AuthContext directly, so it works outside an AuthProvider.
 */
export function useLikeToggle(): (clipId: string) => void {
  const { state, dispatch } = usePlayer()
  const token = useContext(AuthContext)?.accessToken ?? null
  const likedIds = state.likedIds
  const pending = useRef(new Set<string>())

  return useCallback(
    (clipId: string) => {
      if (pending.current.has(clipId)) return
      const liking = !likedIds.includes(clipId)
      dispatch({ type: "like/set", id: clipId, liked: liking })
      if (!token) return
      pending.current.add(clipId)
      saveLike(clipId, liking, token)
        .catch((error: unknown) => {
          if (error instanceof LikeSaveError && error.status === 404) return
          dispatch({ type: "like/set", id: clipId, liked: !liking })
        })
        .finally(() => pending.current.delete(clipId))
    },
    [dispatch, likedIds, token]
  )
}
