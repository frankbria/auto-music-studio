"use client"

import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"

import { useNotifications } from "@/contexts/notifications-context"
import {
  NOTIFICATION_META,
  relativeTime,
  type AppNotification,
} from "@/lib/notifications"
import { cn } from "@/lib/utils"

/**
 * One notification row (US-20.6). A link to the relevant content (AC2); clicking
 * also marks it read (AC3 indicator clears). Distinct icon per type (AC1); an
 * unread dot on the right is the unread indicator.
 */
export function NotificationItem({ notification }: { notification: AppNotification }) {
  const { markRead } = useNotifications()
  const meta = NOTIFICATION_META[notification.type]

  return (
    <Link
      href={notification.href}
      onClick={() => markRead(notification.id)}
      data-testid="notification-item"
      className={cn(
        "flex items-start gap-3 rounded-lg px-3 py-3 outline-none transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50",
        !notification.read && "bg-accent/40"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-muted",
          meta.tone
        )}
      >
        <HugeiconsIcon icon={meta.icon} size={18} aria-hidden />
      </span>

      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block text-sm",
            notification.read ? "text-muted-foreground" : "font-medium text-foreground"
          )}
        >
          {notification.message}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {relativeTime(notification.createdAt)}
        </span>
      </span>

      {!notification.read && (
        <span
          data-testid="unread-dot"
          aria-label="Unread"
          className="mt-2 size-2 shrink-0 rounded-full bg-primary"
        />
      )}
    </Link>
  )
}
