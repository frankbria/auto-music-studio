import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  NotificationsProvider,
  useNotifications,
  useNotify,
} from "@/contexts/notifications-context"

function wrapper({ children }: { children: React.ReactNode }) {
  return <NotificationsProvider>{children}</NotificationsProvider>
}

describe("NotificationsProvider.notify", () => {
  it("prepends an unread notification and bumps the unread count (AC5)", () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    const before = result.current.unreadCount

    act(() => {
      result.current.notify({
        type: "mastering_complete",
        message: 'Mastering complete for "Velvet Static"',
        href: "/release",
      })
    })

    expect(result.current.unreadCount).toBe(before + 1)
    expect(result.current.notifications[0]).toMatchObject({
      type: "mastering_complete",
      read: false,
      href: "/release",
    })
  })
})

describe("useNotify", () => {
  it("degrades to a no-op outside a provider (no throw)", () => {
    const { result } = renderHook(() => useNotify())
    expect(() => result.current({ type: "system", message: "x", href: "/" })).not.toThrow()
  })
})
