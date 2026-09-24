"use client"

import { useEffect, useMemo, useState } from "react"

import { fetchMyAppeals, appealsByClip, type AppealView } from "@/lib/appeals"

/**
 * The signed-in caller's own moderation appeals (US-27.4), fetched once and
 * mapped by clip id (`byClip`) for the workspace clip cards. `refetch` bumps a
 * counter to force a refresh, mirroring useClips' `refreshKey`.
 */
export function useMyAppeals(accessToken: string | null) {
  const [appeals, setAppeals] = useState<AppealView[]>([])
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let active = true
    void (accessToken ? fetchMyAppeals(accessToken) : Promise.resolve([])).then(
      (next) => {
        if (active) setAppeals(next)
      }
    )
    return () => {
      active = false
    }
  }, [accessToken, version])

  const byClip = useMemo(() => appealsByClip(appeals), [appeals])

  return { appeals, byClip, refetch: () => setVersion((v) => v + 1) }
}
