import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  NotificationsProvider,
  useNotifications,
  useNotify,
} from "@/contexts/notifications-context"
import {
  notificationEvent,
  readCalls,
  stubNotificationsApi,
} from "@/test/notifications-api"
import { SIGNED_IN, SignedIn, type AuthValue } from "@/test/signed-in"
import { useMyAppeals } from "@/hooks/use-my-appeals"
import type { NotificationEventView } from "@/lib/notifications"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function renderStore(auth: AuthValue | null = SIGNED_IN) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <SignedIn value={auth}>
      <NotificationsProvider>{children}</NotificationsProvider>
    </SignedIn>
  )
  return renderHook(() => useNotifications(), { wrapper })
}

describe("NotificationsProvider loading (#537)", () => {
  it("loads the signed-in user's notices with the server unread total", async () => {
    const fetchMock = stubNotificationsApi(
      [[notificationEvent("a"), notificationEvent("b", { read: true })]],
      5
    )
    const { result } = renderStore()

    await waitFor(() => expect(result.current.notifications).toHaveLength(2))
    expect(result.current.notifications[0]).toMatchObject({
      id: "a",
      type: "moderation",
      message: 'Moderation removed "Song a". Reason: Reason a',
      href: "/song/clip-a",
    })
    expect(result.current.unreadCount).toBe(5)
    expect(result.current.hasMore).toBe(false)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe("/api/users/me/notifications?offset=0")
    expect((init?.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("stays empty and never calls the API when signed out", async () => {
    const fetchMock = stubNotificationsApi([[notificationEvent("a")]])
    const { result } = renderStore(null)

    await act(async () => {})
    expect(result.current.notifications).toEqual([])
    expect(result.current.unreadCount).toBe(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("loadMore fetches the next offset and drops repeats", async () => {
    const fetchMock = stubNotificationsApi([
      [notificationEvent("a"), notificationEvent("b")],
      [notificationEvent("b"), notificationEvent("c")],
    ])
    const { result } = renderStore()
    await waitFor(() => expect(result.current.hasMore).toBe(true))

    act(() => result.current.loadMore())

    await waitFor(() =>
      expect(result.current.notifications.map((n) => n.id)).toEqual([
        "a",
        "b",
        "c",
      ])
    )
    expect(result.current.hasMore).toBe(false)
    expect(String(fetchMock.mock.calls[1][0])).toBe(
      "/api/users/me/notifications?offset=2"
    )
  })
})

describe("NotificationsProvider reads (#537)", () => {
  it("markRead flips the row, decrements the count, and saves it", async () => {
    const fetchMock = stubNotificationsApi([
      [notificationEvent("a"), notificationEvent("b")],
    ])
    const { result } = renderStore()
    await waitFor(() => expect(result.current.unreadCount).toBe(2))

    act(() => result.current.markRead("a"))

    expect(result.current.notifications[0].read).toBe(true)
    expect(result.current.unreadCount).toBe(1)
    expect(readCalls(fetchMock)).toEqual([{ ids: ["a"] }])
  })

  it("markRead on an already-read row changes nothing locally", async () => {
    stubNotificationsApi([[notificationEvent("a", { read: true })]], 3)
    const { result } = renderStore()
    await waitFor(() => expect(result.current.notifications).toHaveLength(1))

    act(() => result.current.markRead("a"))

    expect(result.current.unreadCount).toBe(3)
  })

  it("markAllRead clears the count and saves every notice", async () => {
    const fetchMock = stubNotificationsApi([[notificationEvent("a")]], 4)
    const { result } = renderStore()
    await waitFor(() => expect(result.current.unreadCount).toBe(4))

    act(() => result.current.markAllRead())

    expect(result.current.unreadCount).toBe(0)
    expect(result.current.notifications.every((n) => n.read)).toBe(true)
    expect(readCalls(fetchMock)).toEqual([{}])
  })
})

describe("NotificationsProvider.notify", () => {
  it("prepends an unread notification and bumps the unread count (AC5)", async () => {
    stubNotificationsApi([[notificationEvent("a")]])
    const { result } = renderStore()
    await waitFor(() => expect(result.current.unreadCount).toBe(1))

    act(() => {
      result.current.notify({
        type: "mastering_complete",
        message: 'Mastering complete for "Velvet Static"',
        href: "/release",
      })
    })

    expect(result.current.unreadCount).toBe(2)
    expect(result.current.notifications[0]).toMatchObject({
      type: "mastering_complete",
      read: false,
      href: "/release",
    })
  })

  it("a live notice is marked read locally only (it has no server id)", async () => {
    const fetchMock = stubNotificationsApi([[]])
    const { result } = renderStore()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    act(() =>
      result.current.notify({ type: "system", message: "x", href: "/" })
    )

    act(() => result.current.markRead(result.current.notifications[0].id))

    expect(result.current.unreadCount).toBe(0)
    expect(readCalls(fetchMock)).toEqual([])
  })
})

describe("NotificationsProvider load vs notify (#537)", () => {
  it("keeps a live notice raised while the first page was loading", async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    const serve = stubNotificationsApi([[notificationEvent("a")]])
    vi.stubGlobal(
      "fetch",
      vi.fn(async (...args: Parameters<typeof fetch>) => {
        await gate
        return serve(...args)
      })
    )
    const { result } = renderStore()

    act(() =>
      result.current.notify({ type: "system", message: "live", href: "/" })
    )
    await act(async () => release())

    await waitFor(() =>
      expect(result.current.notifications.map((n) => n.message)).toEqual([
        "live",
        'Moderation removed "Song a". Reason: Reason a',
      ])
    )
    expect(result.current.unreadCount).toBe(2)
  })
})

describe("NotificationsProvider sign-out (#537)", () => {
  it("drops an older page that lands after the user signed out", async () => {
    const serve = stubNotificationsApi([
      [notificationEvent("a")],
      [notificationEvent("b")],
    ])
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    vi.stubGlobal(
      "fetch",
      vi.fn(async (...args: Parameters<typeof fetch>) => {
        if (String(args[0]).includes("offset=1")) await gate
        return serve(...args)
      })
    )
    let auth: AuthValue | null = SIGNED_IN
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <SignedIn value={auth}>
        <NotificationsProvider>{children}</NotificationsProvider>
      </SignedIn>
    )
    const { result, rerender } = renderHook(() => useNotifications(), {
      wrapper,
    })
    await waitFor(() => expect(result.current.hasMore).toBe(true))

    act(() => result.current.loadMore())
    auth = null
    rerender()
    await waitFor(() => expect(result.current.notifications).toEqual([]))
    await act(async () => release())

    expect(result.current.notifications).toEqual([])
  })
})

describe("useNotify", () => {
  it("degrades to a no-op outside a provider (no throw)", () => {
    const { result } = renderHook(() => useNotify())
    expect(() =>
      result.current({ type: "system", message: "x", href: "/" })
    ).not.toThrow()
  })
})

/** An inbox whose first page can change between requests, as the server's would. */
function liveInbox(
  first: NotificationEventView[],
  older: NotificationEventView[] = []
) {
  const inbox = { first, older, unread: first.filter((e) => !e.read).length }
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost")
      if (init?.method === "POST")
        return new Response(JSON.stringify({ updated: 0 }))
      if (url.pathname.startsWith("/api/users/me/appeals")) {
        return new Response(JSON.stringify({ appeals: [], next_cursor: null }))
      }
      const offset = Number(url.searchParams.get("offset") ?? 0)
      const page = offset === 0 ? inbox.first : inbox.older
      return new Response(
        JSON.stringify({
          notifications: page,
          unread_count: inbox.unread,
          has_more: offset === 0 && inbox.older.length > 0,
        })
      )
    }
  )
  vi.stubGlobal("fetch", fetchMock)
  return { inbox, fetchMock }
}

describe("NotificationsProvider live inbox (#566)", () => {
  it("a notice inserted after the first load appears and bumps the badge when the tab regains focus", async () => {
    const { inbox } = liveInbox([notificationEvent("a")])
    const { result } = renderStore()
    await waitFor(() => expect(result.current.unreadCount).toBe(1))

    inbox.first = [notificationEvent("new"), notificationEvent("a")]
    inbox.unread = 2
    act(() => {
      window.dispatchEvent(new Event("focus"))
    })

    await waitFor(() => expect(result.current.unreadCount).toBe(2))
    expect(result.current.notifications.map((n) => n.id)).toEqual(["new", "a"])
  })

  it("a refresh keeps older pages and live notices already in the store", async () => {
    const { inbox } = liveInbox(
      [notificationEvent("a"), notificationEvent("b")],
      [notificationEvent("c")]
    )
    const { result } = renderStore()
    await waitFor(() => expect(result.current.hasMore).toBe(true))
    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.notifications).toHaveLength(3))
    act(() =>
      result.current.notify({
        type: "mastering_complete",
        message: "m",
        href: "/",
      })
    )

    inbox.first = [notificationEvent("new"), notificationEvent("a")]
    inbox.unread = 4
    act(() => {
      window.dispatchEvent(new Event("focus"))
    })

    await waitFor(() => expect(result.current.notifications).toHaveLength(5))
    expect(result.current.notifications.map((n) => n.id)).toEqual([
      "new",
      "n-live-1",
      "a",
      "b",
      "c",
    ])
    expect(result.current.unreadCount).toBe(5) // four on the server, plus the live one
  })

  it("polls on an interval while signed in", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const { inbox, fetchMock } = liveInbox([notificationEvent("a")])
      const { result } = renderStore()
      await waitFor(() => expect(result.current.unreadCount).toBe(1))
      const before = fetchMock.mock.calls.length

      inbox.first = [notificationEvent("new"), notificationEvent("a")]
      inbox.unread = 2
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000)
      })

      expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
      await waitFor(() => expect(result.current.unreadCount).toBe(2))
    } finally {
      vi.useRealTimers()
    }
  })

  it("an appeal outcome arriving mid-session refetches the Library's appeal status (#543)", async () => {
    const { inbox, fetchMock } = liveInbox([notificationEvent("a")])
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <SignedIn>
        <NotificationsProvider>{children}</NotificationsProvider>
      </SignedIn>
    )
    const { result } = renderHook(
      () => ({ appeals: useMyAppeals("tok"), inbox: useNotifications() }),
      { wrapper }
    )
    const appealFetches = () =>
      fetchMock.mock.calls.filter(([url]) =>
        String(url).startsWith("/api/users/me/appeals")
      ).length
    await waitFor(() => expect(result.current.inbox.unreadCount).toBe(1))
    const before = appealFetches()

    inbox.first = [
      notificationEvent("outcome", {
        event_type: "moderation_appeal_reversed",
      }),
      notificationEvent("a"),
    ]
    inbox.unread = 2
    act(() => {
      window.dispatchEvent(new Event("focus"))
    })

    await waitFor(() => expect(appealFetches()).toBe(before + 1))
  })

  it("a poll that left before Mark all read doesn't restore the old badge", async () => {
    const { inbox, fetchMock } = liveInbox([
      notificationEvent("a"),
      notificationEvent("b"),
    ])
    const { result } = renderStore()
    await waitFor(() => expect(result.current.unreadCount).toBe(2))

    let answer: (r: Response) => void = () => {}
    fetchMock.mockImplementationOnce(
      () => new Promise<Response>((resolve) => (answer = resolve))
    )
    act(() => {
      window.dispatchEvent(new Event("focus"))
    })
    act(() => result.current.markAllRead())
    await act(async () => {
      answer(
        new Response(
          JSON.stringify({
            notifications: [notificationEvent("arrived"), ...inbox.first],
            unread_count: 3,
            has_more: false,
          })
        )
      )
    })

    expect(result.current.unreadCount).toBe(0)
    // Mark all read on the server covered the notice this poll brought in, too.
    expect(
      result.current.notifications.find((n) => n.id === "arrived")?.read
    ).toBe(true)
  })
})
