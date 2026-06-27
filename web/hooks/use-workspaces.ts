"use client"

import { useEffect, useMemo, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { Workspace, WorkspaceListResponse } from "@/lib/workspace-clips"

/**
 * Load the user's workspaces from the BFF (/api/workspaces). Exposes the list
 * plus the default workspace (the one flagged `is_default`, else the first) for
 * the panel breadcrumb and the initial clip query. Use behind an auth guard.
 */
export function useWorkspaces() {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (authLoading || !accessToken) return
    let active = true
    fetch("/api/workspaces", {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as WorkspaceListResponse
      })
      .then((body) => {
        if (active) {
          setWorkspaces(body.workspaces)
          setError(false)
        }
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [accessToken, authLoading])

  const defaultWorkspace = useMemo(
    () => workspaces?.find((w) => w.is_default) ?? workspaces?.[0] ?? null,
    [workspaces]
  )

  const loading = authLoading || (!!accessToken && workspaces === null && !error)

  return { workspaces: workspaces ?? [], defaultWorkspace, loading, error }
}
