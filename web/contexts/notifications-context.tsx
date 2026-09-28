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

import { AuthContext } from "@/contexts/auth-context"
import {
  addNotification as addNotificationIn,
  fetchNotifications,
  markAllRead as markAllReadIn,
  markNotificationsRead,
  markRead as markReadIn,
  type AppNotification,
  type NotifyInput,
} from "@/lib/notifications"

// Notifications store (US-20.6, #537). Lives in the ROOT layout because the unread
// badge renders in the Sidebar while the list + mutations live on /notifications,
// and both must read one reactive source so "mark all as read" clears the badge.
//
// Server rows load when a user signs in; reads are applied optimistically and sent
// to the API. `notify()` rows (e.g. a mastering job completing) are session-only:
// they have no server id, so marking them read stays local.
//
// Reads AuthContext directly (not useAuth, which throws) so suites that render the
// provider without an AuthProvider get an empty, signed-out store.

type NotificationsContextValue = {
  notifications: AppNotification[]
  unreadCount: number
  /** True when older server notifications exist beyond the loaded pages. */
  hasMore: boolean
  /** The first page could not be loaded, so an empty list does not mean "no notices". */
  loadFailed: boolean
  /** Re-request the first page after a failed load. */
  retry: () => void
  loadMore: () => void
  markRead: (id: string) => void
  markAllRead: () => void
  /** Raise a new (unread) notification now — e.g. a mastering job completing (US-21.3). */
  notify: (input: NotifyInput) => void
}

const NotificationsContext = createContext<NotificationsContextValue | null>(
  null
)

const LIVE_PREFIX = "n-live-"
const isLive = (n: AppNotification) => n.id.startsWith(LIVE_PREFIX)

type Store = {
  items: AppNotification[]
  unread: number
  hasMore: boolean
  loadFailed: boolean
}
const EMPTY: Store = { items: [], unread: 0, hasMore: false, loadFailed: false }

export function NotificationsProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const auth = useContext(AuthContext)
  const userId = auth?.user?.id ?? null
  const [store, setStore] = useState<Store>(EMPTY)
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  // The access token rotates mid-session; keying the load on the user (not the
  // token) keeps a rotation from reloading page 1 over pages already revealed.
  const tokenRef = useRef<string | null>(null)
  useEffect(() => {
    tokenRef.current = auth?.accessToken ?? null
  }, [auth?.accessToken])

  // Bumped on every (re)load, so a "Show older" page requested by a previous
  // session (sign-out, another user, retry) is dropped rather than appended.
  const session = useRef(0)

  useEffect(() => {
    let cancelled = false
    session.current += 1
    const load = async () => {
      const token = tokenRef.current
      if (!token) {
        if (!cancelled) setStore(EMPTY)
        return
      }
      const page = await fetchNotifications(token).catch(() => null)
      if (cancelled) return
      if (!page) {
        setStore((s) => ({ ...s, loadFailed: true }))
        return
      }
      // Keep any live rows raised while the request was in flight.
      setStore((s) => {
        const live = s.items.filter(isLive)
        return {
          items: [...live, ...page.notifications],
          unread: page.unreadCount + live.filter((n) => !n.read).length,
          hasMore: page.hasMore,
          loadFailed: false,
        }
      })
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [userId, attempt])

  const serverCount = store.items.filter((n) => !isLive(n)).length
  const loadMore = useCallback(() => {
    const token = tokenRef.current
    if (!token) return
    const requestedIn = session.current
    void fetchNotifications(token, serverCount)
      .then((page) => {
        if (session.current !== requestedIn) return
        setStore((s) => {
          // Offset paging: a notice that arrived since page 1 shifts older rows down,
          // so drop the repeats.
          const seen = new Set(s.items.map((n) => n.id))
          const fresh = page.notifications.filter((n) => !seen.has(n.id))
          return { ...s, items: [...s.items, ...fresh], hasMore: page.hasMore }
        })
      })
      .catch(() => undefined)
  }, [serverCount])

  const markRead = useCallback((id: string) => {
    setStore((s) => {
      const item = s.items.find((n) => n.id === id)
      if (!item || item.read) return s
      return {
        ...s,
        items: markReadIn(s.items, id),
        unread: Math.max(0, s.unread - 1),
      }
    })
    const token = tokenRef.current
    if (token && !id.startsWith(LIVE_PREFIX))
      void markNotificationsRead(token, [id])
  }, [])

  const markAllRead = useCallback(() => {
    setStore((s) => ({ ...s, items: markAllReadIn(s.items), unread: 0 }))
    const token = tokenRef.current
    if (token) void markNotificationsRead(token)
  }, [])

  // Monotonic id source for live notifications, distinct from server ids.
  const seq = useRef(0)
  const notify = useCallback((input: NotifyInput) => {
    seq.current += 1
    const entry: AppNotification = {
      id: `${LIVE_PREFIX}${seq.current}`,
      read: false,
      createdAt: new Date().toISOString(),
      ...input,
    }
    setStore((s) => ({
      ...s,
      items: addNotificationIn(s.items, entry),
      unread: s.unread + 1,
    }))
  }, [])

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications: store.items,
      unreadCount: store.unread,
      hasMore: store.hasMore,
      loadFailed: store.loadFailed,
      retry,
      loadMore,
      markRead,
      markAllRead,
      notify,
    }),
    [store, retry, loadMore, markRead, markAllRead, notify]
  )

  return (
    <NotificationsContext.Provider value={value}>
      {children}
    </NotificationsContext.Provider>
  )
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  if (!ctx)
    throw new Error(
      "useNotifications must be used within a NotificationsProvider"
    )
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
