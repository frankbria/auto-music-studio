"use client"

import { createContext, useCallback, useContext, useMemo, useState } from "react"

import {
  initialNotifications,
  markAllRead as markAllReadIn,
  markRead as markReadIn,
  unreadCount as countUnread,
  type AppNotification,
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

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications,
      unreadCount: countUnread(notifications),
      markRead,
      markAllRead,
    }),
    [notifications, markRead, markAllRead]
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
