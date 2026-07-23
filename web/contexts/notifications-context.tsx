"use client"

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react"

import {
  addNotification as addNotificationIn,
  initialNotifications,
  markAllRead as markAllReadIn,
  markRead as markReadIn,
  unreadCount as countUnread,
  type AppNotification,
  type NotifyInput,
} from "@/lib/notifications"

// In-memory notifications store (US-20.6). Lives in the ROOT layout — unlike the
// route-scoped Playlists store — because the unread-count badge renders in the
// Sidebar (root layout) while the list + mutations live on /notifications, and
// both must read one reactive source so "mark all as read" clears the badge.
// Each action runs the matching pure helper from lib/notifications. Swap the seed
// for a fetch and the actions for PATCH calls when the API exists; surface stays.

type NotificationsContextValue = {
  notifications: AppNotification[]
  unreadCount: number
  markRead: (id: string) => void
  markAllRead: () => void
  /** Raise a new (unread) notification now — e.g. a mastering job completing (US-21.3). */
  notify: (input: NotifyInput) => void
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null)

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<AppNotification[]>(initialNotifications)

  const markRead = useCallback((id: string) => {
    setNotifications((list) => markReadIn(list, id))
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications((list) => markAllReadIn(list))
  }, [])

  // Monotonic id source for live notifications (distinct from the seed's "n-*-N").
  const seq = useRef(0)
  const notify = useCallback((input: NotifyInput) => {
    seq.current += 1
    const entry: AppNotification = {
      id: `n-live-${seq.current}`,
      read: false,
      createdAt: new Date().toISOString(),
      ...input,
    }
    setNotifications((list) => addNotificationIn(list, entry))
  }, [])

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications,
      unreadCount: countUnread(notifications),
      markRead,
      markAllRead,
      notify,
    }),
    [notifications, markRead, markAllRead, notify]
  )

  return (
    <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
  )
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  if (!ctx) throw new Error("useNotifications must be used within a NotificationsProvider")
  return ctx
}

/** Unread count for cross-cutting chrome (the sidebar bell) that can render
 *  outside the provider — e.g. Sidebar/AppShell unit tests. Degrades to 0 (badge
 *  hidden) rather than throwing, so those suites need no provider wrapper. */
export function useUnreadCount(): number {
  return useContext(NotificationsContext)?.unreadCount ?? 0
}

const noop = () => {}

/** Notifier for feature code that raises notifications (e.g. the mastering tab)
 *  but may render in suites without a provider — degrades to a no-op rather than
 *  throwing, mirroring useUnreadCount. */
export function useNotify(): (input: NotifyInput) => void {
  return useContext(NotificationsContext)?.notify ?? noop
}
