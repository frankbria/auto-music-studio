"use client"

import { NotificationItem } from "@/components/notifications/NotificationItem"
import { Button } from "@/components/ui/button"
import { useNotifications } from "@/contexts/notifications-context"

// Notifications page body (US-20.6, #537). Lists activity (moderation notices,
// appeal outcomes, voice training, distribution updates, system) with per-type icons, unread
// indicators, and "Mark all as read". Data + mutations come from the root
// NotificationsProvider, shared with the sidebar bell badge.

// "Infinite scroll" is a Show-older button that fetches the next API page rather
// than an IntersectionObserver.
export function NotificationsView() {
  const {
    notifications,
    unreadCount,
    hasMore,
    loadFailed,
    loadMore,
    markAllRead,
  } = useNotifications()

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Notifications</h1>
          <p className="text-sm text-muted-foreground">
            {unreadCount > 0 ? `${unreadCount} unread` : "You're all caught up"}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={markAllRead}
          disabled={unreadCount === 0}
        >
          Mark all as read
        </Button>
      </header>

      {notifications.length === 0 ? (
        <p className="py-16 text-center text-sm text-muted-foreground">
          {loadFailed
            ? "Could not load your notifications. Try again later."
            : "No notifications yet."}
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {notifications.map((notification) => (
            <li key={notification.id}>
              <NotificationItem notification={notification} />
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <div className="mt-4 flex justify-center">
          <Button variant="ghost" size="sm" onClick={loadMore}>
            Show older notifications
          </Button>
        </div>
      )}
    </div>
  )
}
