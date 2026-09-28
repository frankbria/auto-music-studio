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

describe("useNotify", () => {
  it("degrades to a no-op outside a provider (no throw)", () => {
    const { result } = renderHook(() => useNotify())
    expect(() =>
      result.current({ type: "system", message: "x", href: "/" })
    ).not.toThrow()
  })
})
