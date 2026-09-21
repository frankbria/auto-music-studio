"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { fetchCurrentProfile } from "@/lib/profile-request"

// Admin lookup for the moderation dashboard and its sidebar link (US-27.3),
// modelled on useSubscriptionTier. Fails closed: anything short of an explicit
// `is_admin: true` from the profile is a non-admin. This only decides what to
// render; the backend's require_admin guards every admin endpoint regardless.

export function useIsAdmin() {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [isAdmin, setIsAdmin] = useState(false)
  const [fetched, setFetched] = useState(false)

  useEffect(() => {
    if (authLoading || !accessToken) return
    let active = true
    fetchCurrentProfile(accessToken)
      .then((profile) => {
        if (active) setIsAdmin(profile.is_admin === true)
      })
      .catch(() => {
        // Keep the non-admin default.
      })
      .finally(() => {
        if (active) setFetched(true)
      })
    return () => {
      active = false
    }
  }, [accessToken, authLoading])

  return {
    isAdmin: !!accessToken && isAdmin,
    isLoading: authLoading || (!!accessToken && !fetched),
  }
}
