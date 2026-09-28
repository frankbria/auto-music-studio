// Notifications data seam (US-20.6, #537).
//
// The inbox is the caller's NotificationEvent rows from GET /api/users/me/notifications
// (moderation, appeals, voice training, distribution), mapped to display rows by
// toAppNotification. Reading one stamps it read server-side. The reactive store
// (contexts/notifications-context) drives both the page and the sidebar bell badge.
// No polling: the list loads on sign-in and pages on "Show older".

import type { IconSvgElement } from "@hugeicons/react"
import {
  FavouriteIcon,
  GitBranchIcon,
  Megaphone01Icon,
  MixerIcon,
  MusicNote01Icon,
  SecurityWarningIcon,
  Upload01Icon,
  UserAdd01Icon,
  Video01Icon,
} from "@hugeicons/core-free-icons"

/** The notification kinds (spec section 31, plus video_complete from US-22.3). */
export type NotificationType =
  | "like"
  | "remix"
  | "follow"
  | "generation_complete"
  | "mastering_complete"
  | "video_complete"
  | "distribution_update"
  | "moderation"
  | "system"

/** One notification. `href` is where clicking it navigates (AC2). */
export type AppNotification = {
  id: string
  type: NotificationType
  message: string
  href: string
  /** ISO timestamp; rendered via relativeTime(). */
  createdAt: string
  read: boolean
}

type TypeMeta = { icon: IconSvgElement; tone: string; label: string }

/** Per-type icon + accent tone + short label. Distinct icon per type (AC1). */
export const NOTIFICATION_META: Record<NotificationType, TypeMeta> = {
  like: { icon: FavouriteIcon, tone: "text-rose-500", label: "Like" },
  remix: { icon: GitBranchIcon, tone: "text-violet-500", label: "Remix" },
  follow: { icon: UserAdd01Icon, tone: "text-blue-500", label: "Follower" },
  generation_complete: {
    icon: MusicNote01Icon,
    tone: "text-emerald-500",
    label: "Generation",
  },
  mastering_complete: {
    icon: MixerIcon,
    tone: "text-amber-500",
    label: "Mastering",
  },
  video_complete: {
    icon: Video01Icon,
    tone: "text-fuchsia-500",
    label: "Video",
  },
  distribution_update: {
    icon: Upload01Icon,
    tone: "text-sky-500",
    label: "Distribution",
  },
  moderation: {
    icon: SecurityWarningIcon,
    tone: "text-red-500",
    label: "Moderation",
  },
  system: {
    icon: Megaphone01Icon,
    tone: "text-muted-foreground",
    label: "System",
  },
}

/** The fields a caller supplies to raise a notification; id/createdAt/read are
 *  stamped by the store (see notifications-context `notify`). */
export type NotifyInput = Pick<AppNotification, "type" | "message" | "href">

/** Prepend a new notification (newest first), immutable — the store's insert path. */
export function addNotification(
  list: AppNotification[],
  entry: AppNotification
): AppNotification[] {
  return [entry, ...list]
}

/** Return a new list with the one notification marked read (immutable). */
export function markRead(
  list: AppNotification[],
  id: string
): AppNotification[] {
  return list.map((item) =>
    item.id === id && !item.read ? { ...item, read: true } : item
  )
}

/** Return a new list with every notification marked read (AC4). */
export function markAllRead(list: AppNotification[]): AppNotification[] {
  return list.map((item) => (item.read ? item : { ...item, read: true }))
}

/** Compact relative age, e.g. "just now", "5m ago", "3h ago", "2d ago", "1w ago".
 *  `now` is injectable so callers/tests are deterministic. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return "just now"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return `${Math.floor(d / 7)}w ago`
}

/** One row of GET /api/v1/users/me/notifications. */
export type NotificationEventView = {
  id: string
  event_type: string
  channel: string
  clip_id: string | null
  release_id: string | null
  voice_model_id: string | null
  payload: Record<string, unknown>
  read: boolean
  created_at: string
}

export type NotificationsPage = {
  notifications: AppNotification[]
  unreadCount: number
  hasMore: boolean
}

function text(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key]
  return typeof value === "string" && value.trim() ? value : null
}

function suffix(label: string, value: string | null): string {
  return value ? ` ${label}: ${value}` : ""
}

/** Map a recorded event to a display row. Moderation notices carry the reason. */
export function toAppNotification(
  event: NotificationEventView
): AppNotification {
  const p = event.payload
  const title = text(p, "title")
  const song = title ? `"${title}"` : "your song"
  const songHref = event.clip_id ? `/song/${event.clip_id}` : "/notifications"
  const base = { id: event.id, createdAt: event.created_at, read: event.read }
  const row = (
    type: NotificationType,
    message: string,
    href: string
  ): AppNotification => ({
    ...base,
    type,
    message,
    href,
  })

  switch (event.event_type) {
    case "moderation_clip_removed":
      return row(
        "moderation",
        `Moderation removed ${song}.${suffix("Reason", text(p, "reason"))}`,
        songHref
      )
    case "moderation_warning":
      return row(
        "moderation",
        `You received a moderation warning.${suffix("Reason", text(p, "reason"))}`,
        "/notifications"
      )
    case "moderation_appeal_upheld":
      return row(
        "moderation",
        `Your appeal for ${song} was reviewed and the decision stands.${suffix("Note", text(p, "note"))}`,
        songHref
      )
    case "moderation_appeal_reversed":
      return row(
        "moderation",
        `Your appeal for ${song} was accepted and the decision reversed.${suffix("Note", text(p, "note"))}`,
        songHref
      )
    case "moderation_appeal_info_requested":
      return row(
        "moderation",
        `Moderation needs more information about your appeal for ${song}.${suffix("Note", text(p, "note"))}`,
        songHref
      )
    case "voice_training_complete":
      return row(
        "system",
        `Your voice model "${text(p, "name") ?? "voice"}" is ready.`,
        "/me"
      )
    case "voice_training_failed":
      return row(
        "system",
        `Training failed for voice model "${text(p, "name") ?? "voice"}".${suffix("Error", text(p, "error"))}`,
        "/me"
      )
    case "status_live":
      return row(
        "distribution_update",
        `${song} is now live on ${event.channel}.`,
        "/release"
      )
    case "status_rejected":
      return row(
        "distribution_update",
        `${song} was rejected by ${event.channel}.`,
        "/release"
      )
    default:
      return row("system", "You have a new notification.", "/notifications")
  }
}

export class NotificationsError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
    this.name = "NotificationsError"
  }
}

/** One page of the caller's notifications, newest first. Throws NotificationsError. */
export async function fetchNotifications(
  token: string,
  offset = 0
): Promise<NotificationsPage> {
  const res = await fetch(`/api/users/me/notifications?offset=${offset}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new NotificationsError(
      typeof body?.detail === "string"
        ? body.detail
        : "Could not load notifications.",
      res.status
    )
  }
  return {
    notifications: (body.notifications as NotificationEventView[]).map(
      toAppNotification
    ),
    unreadCount: body.unread_count,
    hasMore: body.has_more,
  }
}

/** Mark the given notifications read server-side, or all of them when `ids` is omitted.
 *  Best effort: the store has already updated optimistically, and an unsaved read just
 *  shows as unread again on the next load. */
export async function markNotificationsRead(
  token: string,
  ids?: string[]
): Promise<void> {
  await fetch("/api/users/me/notifications/read", {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(ids ? { ids } : {}),
  }).catch(() => undefined)
}
