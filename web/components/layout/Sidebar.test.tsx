import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Sidebar } from "@/components/layout"
import { AuthProvider } from "@/contexts/auth-context"
import { NotificationsProvider } from "@/contexts/notifications-context"
import { mainNav } from "@/config/navigation"
import { LAYOUT } from "@/lib/constants/layout"
import { initialNotifications, unreadCount } from "@/lib/notifications"
import { routerMock } from "@/test/router-mock"

// The Sidebar's account menu now reads auth state, so renders need a provider.
function renderSidebar() {
  return render(
    <AuthProvider>
      <Sidebar />
    </AuthProvider>
  )
}

beforeEach(() => {
  routerMock.pathname = "/"
  // AuthProvider attempts a session refresh on mount; resolve it as signed-out.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) })
  )
})

describe("Sidebar navigation (US-15.3)", () => {
  it("renders every main destination as a link to the correct route", () => {
    renderSidebar()
    for (const item of mainNav) {
      const link = screen.getByRole("link", { name: item.label })
      expect(link).toHaveAttribute("href", item.href)
    }
    // Labs is a link, Account is a dialog trigger (button), pinned to the bottom.
    expect(screen.getByRole("link", { name: "Labs" })).toHaveAttribute(
      "href",
      "/labs"
    )
    expect(
      screen.getByRole("button", { name: "Account" })
    ).toBeInTheDocument()
  })

  it("marks the active route and only the active route", () => {
    routerMock.pathname = "/explore"
    renderSidebar()
    expect(screen.getByRole("link", { name: "Explore" })).toHaveAttribute(
      "aria-current",
      "page"
    )
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current"
    )
  })

  it("matches Home only on an exact root path (no false positives)", () => {
    routerMock.pathname = "/create"
    renderSidebar()
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current"
    )
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "aria-current",
      "page"
    )
  })

  it("highlights a parent route for nested paths", () => {
    routerMock.pathname = "/create/advanced"
    renderSidebar()
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "aria-current",
      "page"
    )
  })

  it("starts collapsed (icon-only) and toggles to icon+label mode", async () => {
    const user = userEvent.setup()
    renderSidebar()

    const sidebar = screen.getByTestId("app-sidebar")
    expect(sidebar).toHaveStyle({ width: `${LAYOUT.sidebarWidth}px` })
    // Collapsed: labels are not visible (links still have accessible names).
    expect(screen.queryByText("Explore")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Expand sidebar" }))

    expect(sidebar).toHaveStyle({ width: `${LAYOUT.sidebarExpandedWidth}px` })
    expect(screen.getByText("Explore")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Collapse sidebar" })
    ).toBeInTheDocument()
  })

  it("keeps the expanded state across a route change", async () => {
    const user = userEvent.setup()
    const view = renderSidebar()

    await user.click(screen.getByRole("button", { name: "Expand sidebar" }))
    expect(screen.getByText("Explore")).toBeInTheDocument()

    // Simulate navigation: pathname changes, component re-renders in place.
    routerMock.pathname = "/explore"
    view.rerender(
      <AuthProvider>
        <Sidebar />
      </AuthProvider>
    )

    expect(screen.getByText("Explore")).toBeInTheDocument()
    expect(screen.getByTestId("app-sidebar")).toHaveStyle({
      width: `${LAYOUT.sidebarExpandedWidth}px`,
    })
  })

  it("opens the profile dropdown with all account options", async () => {
    const user = userEvent.setup()
    renderSidebar()

    await user.click(screen.getByRole("button", { name: "Open account menu" }))

    expect(
      await screen.findByRole("menuitem", { name: "Profile" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("menuitem", { name: "Account settings" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("menuitem", { name: "Subscription" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("menuitem", { name: "Log out" })
    ).toBeInTheDocument()
  })

  it("opens the account dialog from the bottom-pinned Account item", async () => {
    const user = userEvent.setup()
    renderSidebar()

    await user.click(screen.getByRole("button", { name: "Account" }))

    expect(await screen.findByRole("dialog")).toBeInTheDocument()
  })
})

describe("Sidebar notifications badge (US-20.6, AC5)", () => {
  it("shows the unread count on the Notifications item when a provider is present", () => {
    render(
      <AuthProvider>
        <NotificationsProvider>
          <Sidebar />
        </NotificationsProvider>
      </AuthProvider>
    )
    const badge = screen.getByTestId("nav-unread-badge")
    expect(badge).toHaveTextContent(String(unreadCount(initialNotifications)))
  })

  it("renders no badge without a provider (degrades to 0)", () => {
    renderSidebar()
    expect(screen.queryByTestId("nav-unread-badge")).not.toBeInTheDocument()
  })
})
