import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { NotificationsView } from "@/components/notifications/NotificationsView"
import { NotificationsProvider } from "@/contexts/notifications-context"
import { initialNotifications, unreadCount } from "@/lib/notifications"

function renderView() {
  return render(
    <NotificationsProvider>
      <NotificationsView />
    </NotificationsProvider>
  )
}

describe("NotificationsView (US-20.6)", () => {
  it("lists notifications with a distinct icon and message per type (AC1)", () => {
    renderView()
    // First page (PAGE_SIZE=5) rendered; each row carries its message + an icon.
    for (const n of initialNotifications.slice(0, 5)) {
      expect(screen.getByText(n.message)).toBeInTheDocument()
    }
    expect(screen.getAllByTestId("notification-item").length).toBe(5)
  })

  it("each row links to the relevant content (AC2)", () => {
    renderView()
    const rows = screen.getAllByTestId("notification-item")
    initialNotifications.slice(0, 5).forEach((n, i) => {
      expect(rows[i]).toHaveAttribute("href", n.href)
    })
  })

  it("shows an unread indicator on unread notifications only (AC3)", () => {
    renderView()
    const shown = initialNotifications.slice(0, 5)
    const unreadInPage = shown.filter((n) => !n.read).length
    expect(screen.getAllByTestId("unread-dot").length).toBe(unreadInPage)
  })

  it("marks a single notification read on click, clearing its dot (AC3)", async () => {
    const user = userEvent.setup()
    renderView()
    const firstUnread = initialNotifications.find((n) => !n.read)!
    const before = screen.getAllByTestId("unread-dot").length
    await user.click(screen.getByText(firstUnread.message))
    expect(screen.getAllByTestId("unread-dot").length).toBe(before - 1)
  })

  it('"Mark all as read" clears every unread indicator and disables itself (AC4)', async () => {
    const user = userEvent.setup()
    renderView()
    expect(unreadCount(initialNotifications)).toBeGreaterThan(0)
    const button = screen.getByRole("button", { name: "Mark all as read" })
    expect(button).toBeEnabled()
    await user.click(button)
    expect(screen.queryAllByTestId("unread-dot")).toHaveLength(0)
    expect(button).toBeDisabled()
    expect(screen.getByText("You're all caught up")).toBeInTheDocument()
  })

  it("reveals older notifications in pages (infinite-scroll substitute)", async () => {
    const user = userEvent.setup()
    renderView()
    expect(screen.getAllByTestId("notification-item").length).toBe(5)
    await user.click(screen.getByRole("button", { name: "Show older notifications" }))
    expect(screen.getAllByTestId("notification-item").length).toBe(
      initialNotifications.length
    )
    // All revealed → the reveal button is gone.
    expect(
      screen.queryByRole("button", { name: "Show older notifications" })
    ).not.toBeInTheDocument()
  })
})
