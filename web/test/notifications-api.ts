import { vi } from "vitest"

import type { NotificationEventView } from "@/lib/notifications"

// Stubs the same-origin notifications BFF (#537): GET serves `pages` by offset
// (each page's `has_more` is whether another page follows), POST .../read answers
// {updated: 0}. The returned mock records every call for assertions.

export function notificationEvent(
  id: string,
  overrides: Partial<NotificationEventView> = {}
): NotificationEventView {
  return {
    id,
    event_type: "moderation_clip_removed",
    channel: "in_app",
    clip_id: `clip-${id}`,
    release_id: null,
    voice_model_id: null,
    payload: { title: `Song ${id}`, reason: `Reason ${id}` },
    read: false,
    created_at: "2026-09-28T10:00:00Z",
    ...overrides,
  }
}

export function stubNotificationsApi(
  pages: NotificationEventView[][],
  unreadCount?: number
) {
  const all = pages.flat()
  const unread = unreadCount ?? all.filter((e) => !e.read).length
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost")
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ updated: 0 }), { status: 200 })
      }
      const offset = Number(url.searchParams.get("offset") ?? 0)
      let seen = 0
      const index = pages.findIndex((page) => {
        const hit = seen === offset
        seen += page.length
        return hit
      })
      const page = index === -1 ? [] : pages[index]
      return new Response(
        JSON.stringify({
          notifications: page,
          unread_count: unread,
          has_more: index !== -1 && index < pages.length - 1,
        }),
        { status: 200 }
      )
    }
  )
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

/** The JSON bodies of every POST to the mark-read route, in order. */
export function readCalls(
  fetchMock: ReturnType<typeof stubNotificationsApi>
): unknown[] {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === "POST")
    .map(([url, init]) => {
      if (!String(url).endsWith("/api/users/me/notifications/read"))
        throw new Error(`unexpected POST ${url}`)
      return JSON.parse(String(init?.body))
    })
}
