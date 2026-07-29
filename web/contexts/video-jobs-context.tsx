"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { useAuth } from "@/hooks/use-auth"
import { useNotify } from "@/contexts/notifications-context"
import { fetchVideoStatus } from "@/lib/video"

// App-level watcher for in-flight video renders (US-22.3 AC2). Video generation
// runs for minutes; a render can finish long after the user has left the create
// page. The page-scoped useVideoJob poll dies on unmount, so this provider —
// mounted in the ROOT layout, like NotificationsProvider — keeps polling every
// tracked job across client-side navigation and raises the completion
// notification whenever one finishes, wherever the user has wandered.
//
// It is the SINGLE source of video-completion notifications: the create page
// registers a job via track() and never notifies itself, so a job notifies
// exactly once whether or not its page is still mounted.
//
// ponytail: in-memory only. This survives SPA navigation (the layout never
// remounts) but not a full page reload — a reload drops the watch list. Persist
// to localStorage if reload-durable notifications become a requirement.

const POLL_INTERVAL_MS = 3000

type TrackedJob = { jobId: string; songId: string }

type VideoJobsContextValue = {
  /** Start watching a submitted render so its completion notifies globally. Idempotent. */
  track: (job: TrackedJob) => void
}

const VideoJobsContext = createContext<VideoJobsContextValue | null>(null)

export function VideoJobsProvider({ children }: { children: React.ReactNode }) {
  const { accessToken } = useAuth()
  const notify = useNotify()
  const [active, setActive] = useState<TrackedJob[]>([])

  // Refs so the single poll loop reads the latest token/watch-list without
  // re-subscribing (the token rotates mid-session, #285).
  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  const activeRef = useRef(active)
  useEffect(() => {
    activeRef.current = active
  }, [active])

  // Keep notify in a ref too, so the poll loop can depend on nothing and mount
  // exactly once — a reset of that timer would restart the delay and (if notify
  // were ever non-stable) could drop a completion. Matches tokenRef/activeRef.
  const notifyRef = useRef(notify)
  useEffect(() => {
    notifyRef.current = notify
  }, [notify])

  const track = useCallback((job: TrackedJob) => {
    setActive((list) => (list.some((j) => j.jobId === job.jobId) ? list : [...list, job]))
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    async function tick() {
      const token = tokenRef.current
      // Poll each tracked job once per tick. Sequential is fine: the watch list
      // is tiny (a user renders a handful of videos, not hundreds).
      for (const job of activeRef.current) {
        if (!token) break
        const result = await fetchVideoStatus(job.jobId, token)
        if (cancelled) return
        if (result.kind === "complete") {
          notifyRef.current({
            type: "video_complete",
            message: "Your music video is ready.",
            href: `/video/${job.songId}`,
          })
          setActive((list) => list.filter((j) => j.jobId !== job.jobId))
        } else if (result.kind === "failed" || result.kind === "unauthorized") {
          // Terminal-but-not-complete: stop watching. The create page surfaces
          // the error inline; a global "it failed" toast would be noise.
          setActive((list) => list.filter((j) => j.jobId !== job.jobId))
        }
      }
      if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS)
    }

    timer = setTimeout(tick, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // Depends on nothing: the loop reads token/watch-list/notify through refs, so
    // it mounts once and never restarts its timer.
  }, [])

  const value = useMemo<VideoJobsContextValue>(() => ({ track }), [track])
  return <VideoJobsContext.Provider value={value}>{children}</VideoJobsContext.Provider>
}

/** Register a render for global completion-notification. Degrades to a no-op
 *  outside the provider (e.g. component suites without the root layout), like
 *  useNotify — so callers need no provider wrapper to render. */
export function useVideoJobs(): VideoJobsContextValue {
  return useContext(VideoJobsContext) ?? noopValue
}

const noopValue: VideoJobsContextValue = { track: () => {} }
