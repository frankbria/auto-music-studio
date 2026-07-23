// Notifications data seam (US-20.6).
//
// Like Explore (US-20.1), Search (US-20.2), Playlists (US-20.3), the Feed
// (US-20.4), and Profiles (US-20.5), the notifications page has no backend: there
// is no GET /notifications endpoint and no per-type event stream. This module is
// the local, typed mock layer whose shapes mirror the eventual notifications API.
// The reactive store (contexts/notifications-context) drives both the page and the
// sidebar bell badge off this seed + these pure helpers. When the API lands, swap
// the seed for a fetch and the helpers for PATCH calls — callers won't change.
//
// ponytail: session-scoped, synchronous, no persistence and no polling — there is
// nothing to poll against yet. Real-time updates arrive with the real endpoint.

import type { IconSvgElement } from "@hugeicons/react"
import {
  FavouriteIcon,
  GitBranchIcon,
  Megaphone01Icon,
  MixerIcon,
  MusicNote01Icon,
  Upload01Icon,
  UserAdd01Icon,
} from "@hugeicons/core-free-icons"

/** The seven notification kinds from spec section 31. */
export type NotificationType =
  | "like"
  | "remix"
  | "follow"
  | "generation_complete"
  | "mastering_complete"
  | "distribution_update"
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
  mastering_complete: { icon: MixerIcon, tone: "text-amber-500", label: "Mastering" },
  distribution_update: { icon: Upload01Icon, tone: "text-sky-500", label: "Distribution" },
  system: { icon: Megaphone01Icon, tone: "text-muted-foreground", label: "System" },
}

const MINUTE = 60_000

/** Seed notifications — one of every type, mixing read + unread, linking to real
 *  content (song ids from the Explore pool, @handles from Profiles). Timestamps
 *  are relative to load so the demo always shows fresh "Xm/Xh ago" values. */
export const initialNotifications: AppNotification[] = [
  {
    id: "n-like-1",
    type: "like",
    message: 'Ember liked your song "Neon Overdrive"',
    href: "/song/g-electronic",
    createdAt: minutesAgo(4),
    read: false,
  },
  {
    id: "n-remix-1",
    type: "remix",
    message: 'Sol remixed your song "Midnight Circuit"',
    href: "/song/g-rock",
    createdAt: minutesAgo(38),
    read: false,
  },
  {
    id: "n-follow-1",
    type: "follow",
    message: "Nova started following you",
    href: "/@nova",
    createdAt: minutesAgo(3 * 60),
    read: false,
  },
  {
    id: "n-gen-1",
    type: "generation_complete",
    message: 'Your song "Golden Hour" finished generating',
    href: "/song/g-pop",
    createdAt: minutesAgo(5 * 60),
    read: true,
  },
  {
    id: "n-master-1",
    type: "mastering_complete",
    message: 'Mastering complete for "Velvet Skyline"',
    href: "/release",
    createdAt: minutesAgo(26 * 60),
    read: true,
  },
  {
    id: "n-dist-1",
    type: "distribution_update",
    message: '"Neon Overdrive" is now live on Spotify',
    href: "/release",
    createdAt: minutesAgo(2 * 24 * 60),
    read: true,
  },
  {
    id: "n-sys-1",
    type: "system",
    message: "New: collaborative playlists are here — give them a try.",
    href: "/explore",
    createdAt: minutesAgo(9 * 24 * 60),
    read: false,
  },
]

function minutesAgo(min: number): string {
  return new Date(Date.now() - min * MINUTE).toISOString()
}

/** Count of unread notifications — drives the sidebar bell badge (AC5). */
export function unreadCount(list: AppNotification[]): number {
  return list.reduce((n, item) => n + (item.read ? 0 : 1), 0)
}

/** Return a new list with the one notification marked read (immutable). */
export function markRead(list: AppNotification[], id: string): AppNotification[] {
  return list.map((item) => (item.id === id && !item.read ? { ...item, read: true } : item))
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
