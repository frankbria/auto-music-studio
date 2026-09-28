import { describe, expect, it } from "vitest"

import {
  addNotification,
  markAllRead,
  markRead,
  NOTIFICATION_META,
  relativeTime,
  toAppNotification,
  type AppNotification,
  type NotificationEventView,
  type NotificationType,
} from "@/lib/notifications"

const ALL_TYPES: NotificationType[] = [
  "like",
  "remix",
  "follow",
  "generation_complete",
  "mastering_complete",
  "distribution_update",
  "moderation",
  "system",
]

const list: AppNotification[] = ["a", "b", "c"].map((id) => ({
  id,
  type: "system",
  message: `message ${id}`,
  href: "/notifications",
  createdAt: "2026-09-28T00:00:00Z",
  read: false,
}))

function event(
  overrides: Partial<NotificationEventView>
): NotificationEventView {
  return {
    id: "e1",
    event_type: "moderation_clip_removed",
    channel: "in_app",
    clip_id: null,
    release_id: null,
    voice_model_id: null,
    payload: {},
    read: false,
    created_at: "2026-09-28T10:00:00Z",
    ...overrides,
  }
}

describe("toAppNotification (#537)", () => {
  it("shows a removed clip's title and reason, linking to the song", () => {
    const row = toAppNotification(
      event({
        clip_id: "c1",
        payload: {
          clip_id: "c1",
          title: "Takedown",
          reason: "Copyrighted sample",
        },
      })
    )
    expect(row).toEqual({
      id: "e1",
      type: "moderation",
      message: 'Moderation removed "Takedown". Reason: Copyrighted sample',
      href: "/song/c1",
      createdAt: "2026-09-28T10:00:00Z",
      read: false,
    })
  })

  it("shows a warning's reason", () => {
    const row = toAppNotification(
      event({
        event_type: "moderation_warning",
        payload: { reason: "Mislabelled uploads" },
      })
    )
    expect(row.type).toBe("moderation")
    expect(row.message).toBe(
      "You received a moderation warning. Reason: Mislabelled uploads"
    )
  })

  it("omits the reason clause when an admin gave none", () => {
    const row = toAppNotification(
      event({ clip_id: "c1", payload: { title: "Takedown", reason: null } })
    )
    expect(row.message).toBe('Moderation removed "Takedown".')
  })

  it.each([
    [
      "moderation_appeal_upheld",
      'Your appeal for "Song" was reviewed and the decision stands. Note: Still infringing',
    ],
    [
      "moderation_appeal_reversed",
      'Your appeal for "Song" was accepted and the decision reversed. Note: Still infringing',
    ],
    [
      "moderation_appeal_info_requested",
      'Moderation needs more information about your appeal for "Song". Note: Still infringing',
    ],
  ])("words the %s appeal outcome with the admin note", (type, message) => {
    const row = toAppNotification(
      event({
        event_type: type,
        clip_id: "c1",
        payload: { title: "Song", note: "Still infringing" },
      })
    )
    expect(row).toMatchObject({ type: "moderation", message, href: "/song/c1" })
  })

  it("maps voice training and distribution events", () => {
    expect(
      toAppNotification(
        event({
          event_type: "voice_training_failed",
          payload: { name: "Alto", error: "Too short" },
        })
      )
    ).toMatchObject({
      type: "system",
      message: 'Training failed for voice model "Alto". Error: Too short',
      href: "/me",
    })
    expect(
      toAppNotification(
        event({
          event_type: "status_live",
          channel: "soundcloud",
          payload: { title: "Neon" },
        })
      )
    ).toMatchObject({
      type: "distribution_update",
      message: '"Neon" is now live on soundcloud.',
      href: "/release",
    })
  })

  it("falls back to a generic system row for an unknown event", () => {
    expect(
      toAppNotification(event({ event_type: "something_new" }))
    ).toMatchObject({
      type: "system",
      href: "/notifications",
    })
  })

  it("carries the server read flag", () => {
    expect(toAppNotification(event({ read: true })).read).toBe(true)
  })
})

describe("notifications helpers", () => {
  it("maps every type to a distinct icon + label (AC1)", () => {
    const icons = ALL_TYPES.map((t) => NOTIFICATION_META[t].icon)
    expect(new Set(icons).size).toBe(ALL_TYPES.length)
    expect(ALL_TYPES.every((t) => NOTIFICATION_META[t].label.length > 0)).toBe(
      true
    )
  })

  it("carries meta for the video_complete type (US-22.3)", () => {
    expect(NOTIFICATION_META.video_complete.label).toBe("Video")
    expect(NOTIFICATION_META.video_complete.icon).toBeDefined()
    expect(NOTIFICATION_META.video_complete.tone.length).toBeGreaterThan(0)
  })

  it("markRead flips one item immutably, leaving the rest untouched", () => {
    const next = markRead(list, list[1].id)
    expect(next[1].read).toBe(true)
    expect(next[0].read).toBe(false)
    expect(next).not.toBe(list)
    expect(list[1].read).toBe(false) // original unchanged
    // Unrelated items keep identity (no needless re-render churn).
    expect(next[0]).toBe(list[0])
  })

  it("markAllRead clears every unread indicator (AC4)", () => {
    expect(markAllRead(list).every((n) => n.read)).toBe(true)
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

  it("addNotification prepends immutably (newest first)", () => {
    const base = list.slice(0, 2)
    const entry: AppNotification = {
      id: "n-live-1",
      type: "mastering_complete",
      message: "Mastering complete",
      href: "/release",
      createdAt: "2026-07-23T00:00:00Z",
      read: false,
    }
    const next = addNotification(base, entry)
    expect(next).toHaveLength(3)
    expect(next[0]).toBe(entry)
    expect(base).toHaveLength(2) // original untouched
  })
})
