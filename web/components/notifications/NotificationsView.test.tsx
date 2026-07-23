import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { NotificationsView, PAGE_SIZE } from "@/components/notifications/NotificationsView"
import { NotificationsProvider } from "@/contexts/notifications-context"
import { initialNotifications, unreadCount } from "@/lib/notifications"

const firstPage = initialNotifications.slice(0, PAGE_SIZE)

function renderView() {
  return render(
    <NotificationsProvider>
      <NotificationsView />
    </NotificationsProvider>
  )
}

describe("NotificationsView (US-20.6)", () => {
  it("lists the first page of notifications with a message per row, all types on page 1 (AC1)", () => {
    renderView()
    for (const n of firstPage) {
      expect(screen.getByText(n.message)).toBeInTheDocument()
    }
    expect(screen.getAllByTestId("notification-item").length).toBe(firstPage.length)
    // AC1: every notification type is represented on the first page.
    expect(new Set(firstPage.map((n) => n.type)).size).toBe(7)
  })

  it("each row links to the relevant content (AC2)", () => {
    renderView()
    const rows = screen.getAllByTestId("notification-item")
    firstPage.forEach((n, i) => {
      expect(rows[i]).toHaveAttribute("href", n.href)
    })
  })

  it("shows an unread indicator on unread notifications only (AC3)", () => {
    renderView()
    const unreadInPage = firstPage.filter((n) => !n.read).length
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
    expect(screen.getAllByTestId("notification-item").length).toBe(PAGE_SIZE)
    expect(initialNotifications.length).toBeGreaterThan(PAGE_SIZE) // reveal is real
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
