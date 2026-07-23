import { describe, expect, it } from "vitest"

import { getAllClips } from "@/lib/explore"
import {
  initialNotifications,
  markAllRead,
  markRead,
  NOTIFICATION_META,
  relativeTime,
  unreadCount,
  type NotificationType,
} from "@/lib/notifications"
import { getProfileByHandle } from "@/lib/profiles"

const ALL_TYPES: NotificationType[] = [
  "like",
  "remix",
  "follow",
  "generation_complete",
  "mastering_complete",
  "distribution_update",
  "system",
]

describe("notifications seam", () => {
  it("seeds one of every notification type, each with an href and message (AC1, AC2)", () => {
    const types = new Set(initialNotifications.map((n) => n.type))
    for (const t of ALL_TYPES) expect(types.has(t)).toBe(true)
    expect(initialNotifications.every((n) => n.message && n.href)).toBe(true)
  })

  it("every notification links to real, resolvable content — no dead ends (AC2)", () => {
    // Guards against linking a Genre.id (g-*) or unknown handle as a /song or
    // /@profile target, which would dead-end on "not found".
    const clipIds = new Set(getAllClips().map((c) => c.id))
    const staticRoutes = new Set(["/release", "/explore"])
    for (const n of initialNotifications) {
      const where = `${n.id} → ${n.href}`
      if (n.href.startsWith("/song/")) {
        expect(clipIds.has(n.href.slice("/song/".length)), where).toBe(true)
      } else if (n.href.startsWith("/@")) {
        expect(getProfileByHandle(n.href.slice(1)), where).not.toBeNull()
      } else {
        expect(staticRoutes.has(n.href), where).toBe(true)
      }
    }
  })

  it("maps every type to a distinct icon + label (AC1)", () => {
    const icons = ALL_TYPES.map((t) => NOTIFICATION_META[t].icon)
    expect(new Set(icons).size).toBe(ALL_TYPES.length)
    expect(ALL_TYPES.every((t) => NOTIFICATION_META[t].label.length > 0)).toBe(true)
  })

  it("counts only unread (AC5)", () => {
    const list = [
      { ...initialNotifications[0], read: false },
      { ...initialNotifications[1], read: true },
      { ...initialNotifications[2], read: false },
    ]
    expect(unreadCount(list)).toBe(2)
  })

  it("markRead flips one item immutably, leaving the rest untouched", () => {
    const list = initialNotifications.map((n) => ({ ...n, read: false }))
    const next = markRead(list, list[1].id)
    expect(next[1].read).toBe(true)
    expect(next[0].read).toBe(false)
    expect(next).not.toBe(list)
    expect(list[1].read).toBe(false) // original unchanged
    // Unrelated items keep identity (no needless re-render churn).
    expect(next[0]).toBe(list[0])
  })

  it("markAllRead clears every unread indicator (AC4)", () => {
    const list = initialNotifications.map((n) => ({ ...n, read: false }))
    expect(unreadCount(markAllRead(list))).toBe(0)
  })

  it("relativeTime buckets ages deterministically", () => {
    const now = new Date("2026-07-22T12:00:00Z").getTime()
    const at = (ms: number) => new Date(now - ms).toISOString()
    expect(relativeTime(at(5_000), now)).toBe("just now")
    expect(relativeTime(at(5 * 60_000), now)).toBe("5m ago")
    expect(relativeTime(at(3 * 3_600_000), now)).toBe("3h ago")
    expect(relativeTime(at(2 * 86_400_000), now)).toBe("2d ago")
    expect(relativeTime(at(9 * 86_400_000), now)).toBe("1w ago")
  })
})
