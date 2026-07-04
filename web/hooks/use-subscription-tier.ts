"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"

// Reusable subscription-tier lookup (US-17.2). ModelSelectionProvider fetches
// the same profile but is mounted only on the Create page; pages that just need
// the tier (e.g. song detail's Pro-gated actions) use this instead of mounting
// the whole model-selection context. Defaults to "free" until proven otherwise,
// mirroring the provider — a fetch failure must never unlock Pro features.

export function useSubscriptionTier() {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [tier, setTier] = useState("free")
  const [fetched, setFetched] = useState(false)

  useEffect(() => {
    if (authLoading || !accessToken) return
    let active = true
    // Bound the fetch like the model-selection provider does — a hung profile
    // request must not leave Pro menu items locked indefinitely; on timeout the
    // catch keeps the free default and finally resolves the loading state.
    fetch("/api/users/me", {
      headers: { authorization: `Bearer ${accessToken}` },
      signal: AbortSignal.timeout(5000),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("profile fetch failed")
        const profile = (await res.json()) as { subscription_tier?: string }
        if (active && profile.subscription_tier) setTier(profile.subscription_tier)
      })
      .catch(() => {
        // Keep the free default.
      })
      .finally(() => {
        if (active) setFetched(true)
      })
    return () => {
      active = false
    }
  }, [accessToken, authLoading])

  const isLoading = !!accessToken && !authLoading && !fetched
  // Same rule as ModelSelector: anything that isn't exactly "pro" is free.
  return { tier, isFreeTier: tier !== "pro", isLoading }
}
