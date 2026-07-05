"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { ClipLineageResponse, LineageNode } from "@/lib/lineage"

/**
 * Fetch a clip's ancestry from the same-origin BFF (/api/clips/{id}/lineage) for
 * the song-detail "Generation history" panel (US-17.7). Mirrors useSimilarClips:
 * empty/error both resolve quietly (lineage is supplementary) and the result is
 * tagged with the id it belongs to so the page — which stays mounted across
 * /song/:id navigations — never shows the previous song's ancestry under a new
 * clip while its fetch is in flight.
 */
type Result = {
  id: string
  nodes: LineageNode[]
  truncated: boolean
  error: boolean
}

export function useLineage(id: string | undefined) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    if (authLoading || !accessToken || !id) return
    let active = true
    fetch(`/api/clips/${encodeURIComponent(id)}/lineage`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as ClipLineageResponse
      })
      .then((next) => {
        if (active) {
          setResult({
            id,
            nodes: next.nodes ?? [],
            truncated: !!next.depth_truncated,
            error: false,
          })
        }
      })
      .catch(() => {
        if (active) setResult({ id, nodes: [], truncated: false, error: true })
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading])

  const matches = result !== null && result.id === id
  const nodes = matches ? result.nodes : []
  const truncated = matches && result.truncated
  const error = matches && result.error
  const loading = authLoading || (!!accessToken && !!id && !matches)

  return { nodes, truncated, loading, error }
}
