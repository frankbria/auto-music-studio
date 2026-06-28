"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { Clip } from "@/lib/workspace-clips"

/**
 * Fetch a single clip from the same-origin BFF (/api/clips/{id}) with the
 * in-memory access token. Used by the song-detail page (US-17.1). Refetches when
 * `id` changes. A 404 surfaces as `notFound` (distinct from a transient `error`)
 * so the page can show a "song not found" state instead of a generic failure.
 * Use behind an auth guard (e.g. useRequireAuth).
 */
export function useClip(id: string | undefined) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [clip, setClip] = useState<Clip | null>(null)
  const [error, setError] = useState(false)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (authLoading || !accessToken || !id) return
    let active = true
    fetch(`/api/clips/${encodeURIComponent(id)}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (res.status === 404) {
          // Reset in the async callback, not the effect body (lint:
          // react-hooks/set-state-in-effect).
          if (active) {
            setNotFound(true)
            setError(false)
          }
          return null
        }
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as Clip
      })
      .then((next) => {
        if (active && next) {
          setClip(next)
          setError(false)
          setNotFound(false)
        }
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading])

  const loading =
    authLoading || (!!accessToken && !!id && clip === null && !error && !notFound)

  return { clip, loading, error, notFound }
}
