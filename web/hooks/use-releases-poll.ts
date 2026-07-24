"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { fetchReleases, type ReleaseSummary } from "@/lib/releases"

/** Default poll cadence — matches the spec's "real-time-ish" status refresh. */
export const DEFAULT_POLL_INTERVAL_MS = 30_000

export type UseReleasesPoll = {
  releases: ReleaseSummary[] | null
  loading: boolean
  error: string | null
  /** Epoch ms of the last successful load, or null before the first. */
  lastUpdated: number | null
  /** Force an immediate reload (e.g. after a submit). */
  refresh: () => void
}

/**
 * Polls the release listing for live status updates (US-21.6, AC: "status
 * updates via real-time polling"). Refetches every `intervalMs`, but only while
 * the tab is visible (Page Visibility API) so a backgrounded dashboard doesn't
 * poll needlessly — and refetches once immediately when the tab regains focus so
 * a returning user sees fresh state without waiting a full interval.
 *
 * Today `fetchReleases` returns a local seam; the transport is real, so when the
 * backend `GET /releases` is wired in there, live transitions flow through here
 * unchanged. Mirrors use-mastering-job's mounted-ref/timer discipline.
 */
export function useReleasesPoll(intervalMs: number = DEFAULT_POLL_INTERVAL_MS): UseReleasesPoll {
  const [releases, setReleases] = useState<ReleaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)

  // False once unmounted; every post-await branch checks it before setState.
  const mountedRef = useRef(true)
  // Monotonic request id: load() fires from four sources (mount, interval,
  // visibilitychange, refresh) with nothing serializing them, so a slower older
  // fetch could resolve after a newer one. Each call captures its id and drops
  // its result if a newer load has since started — no stale overwrite.
  const seqRef = useRef(0)

  const load = useCallback(async () => {
    const seq = ++seqRef.current
    try {
      const list = await fetchReleases()
      if (!mountedRef.current || seq !== seqRef.current) return
      setReleases(list)
      setError(null)
      setLastUpdated(Date.now())
    } catch {
      if (!mountedRef.current || seq !== seqRef.current) return
      setError("Could not load releases. Please try again.")
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    // Kick the first load off the effect body: a direct call trips
    // react-hooks/set-state-in-effect (the rule can't see the setState is
    // post-await). A microtask still runs before paint.
    queueMicrotask(() => void load())

    const timer = setInterval(() => {
      // Only poll when the tab is visible.
      if (typeof document !== "undefined" && document.hidden) return
      void load()
    }, intervalMs)

    // Refetch immediately on returning to the tab (don't wait a full interval).
    const onVisible = () => {
      if (!document.hidden) void load()
    }
    document.addEventListener("visibilitychange", onVisible)

    return () => {
      mountedRef.current = false
      clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [load, intervalMs])

  const refresh = useCallback(() => void load(), [load])

  return {
    releases,
    loading: releases === null && error === null,
    error,
    lastUpdated,
    refresh,
  }
}
