"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { Clip } from "@/lib/workspace-clips"

type Outcome =
  | { id: string; kind: "ok"; clip: Clip }
  | { id: string; kind: "error" }
  | { id: string; kind: "notFound" }

/**
 * Fetch a single clip from the same-origin BFF (/api/clips/{id}) with the
 * in-memory access token. Used by the song-detail page (US-17.1). Refetches when
 * `id` changes. A 404 surfaces as `notFound` (distinct from a transient `error`)
 * so the page can show a "song not found" state instead of a generic failure.
 * Use behind an auth guard (e.g. useRequireAuth).
 *
 * The fetch outcome is tagged with the id it belongs to. The page component
 * stays mounted across /song/:id navigations, so an outcome whose id no longer
 * matches the requested one is treated as "not loaded yet" — this keeps the page
 * from showing the previous song under the new URL while the new fetch is in
 * flight (it falls back to the loading state instead of stale data).
 */
export function useClip(id: string | undefined) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    if (authLoading || !accessToken || !id) return
    let active = true
    fetch(`/api/clips/${encodeURIComponent(id)}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (res.status === 404) {
          if (active) setOutcome({ id, kind: "notFound" })
          return
        }
        if (!res.ok) throw new Error("fetch failed")
        const clip = (await res.json()) as Clip
        if (active) setOutcome({ id, kind: "ok", clip })
      })
      .catch(() => {
        if (active) setOutcome({ id, kind: "error" })
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading])

  const current = outcome?.id === id ? outcome : null
  const clip = current?.kind === "ok" ? current.clip : null
  const error = current?.kind === "error"
  const notFound = current?.kind === "notFound"
  const loading =
    authLoading || (!!accessToken && !!id && current === null)

  return { clip, loading, error, notFound }
}
