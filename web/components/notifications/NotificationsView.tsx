"use client"

import { useState } from "react"

import { NotificationItem } from "@/components/notifications/NotificationItem"
import { Button } from "@/components/ui/button"
import { useNotifications } from "@/contexts/notifications-context"

// Notifications page body (US-20.6). Lists activity (likes, remixes, followers,
// generation/mastering/distribution updates, system) with per-type icons, unread
// indicators, and "Mark all as read". Data + mutations come from the root
// NotificationsProvider, shared with the sidebar bell badge.

// The seed is 7 items, so "infinite scroll" is a Show-older reveal in PAGE_SIZE
// chunks rather than an IntersectionObserver — the real feed (US-20.4) already has
// the observer; swap this for a cursor fetch when the API lands.
const PAGE_SIZE = 5

export function NotificationsView() {
  const { notifications, unreadCount, markAllRead } = useNotifications()
  const [visible, setVisible] = useState(PAGE_SIZE)
  const shown = notifications.slice(0, visible)

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
          No notifications yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {shown.map((notification) => (
            <li key={notification.id}>
              <NotificationItem notification={notification} />
            </li>
          ))}
        </ul>
      )}

      {visible < notifications.length && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setVisible((v) => v + PAGE_SIZE)}
          >
            Show older notifications
          </Button>
        </div>
      )}
    </div>
  )
}
