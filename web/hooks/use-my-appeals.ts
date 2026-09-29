"use client"

import { useEffect, useMemo, useState } from "react"

import { useLatestNoticeId } from "@/contexts/notifications-context"
import { fetchMyAppeals, appealsByClip, type AppealView } from "@/lib/appeals"

/**
 * The signed-in caller's own moderation appeals (US-27.4), fetched once and
 * mapped by clip id (`byClip`) for the workspace clip cards. `refetch` bumps a
 * counter to force a refresh, mirroring useClips' `refreshKey`. A new
 * moderation notice (an appeal outcome) refetches too (#543).
 */
export function useMyAppeals(accessToken: string | null) {
  const [appeals, setAppeals] = useState<AppealView[]>([])
  const [version, setVersion] = useState(0)
  const latestNotice = useLatestNoticeId("moderation")

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
  }, [accessToken, version, latestNotice])

  const byClip = useMemo(() => appealsByClip(appeals), [appeals])

  return { appeals, byClip, refetch: () => setVersion((v) => v + 1) }
}
