import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"

import { Sidebar } from "@/components/layout"
import { mainNav } from "@/config/navigation"
import { LAYOUT } from "@/lib/constants/layout"
import { routerMock } from "@/test/router-mock"

beforeEach(() => {
  routerMock.pathname = "/"
})

describe("Sidebar navigation (US-15.3)", () => {
  it("renders every main destination as a link to the correct route", () => {
    render(<Sidebar />)
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
    render(<Sidebar />)
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
    render(<Sidebar />)
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
    render(<Sidebar />)
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "aria-current",
      "page"
    )
  })

  it("starts collapsed (icon-only) and toggles to icon+label mode", async () => {
    const user = userEvent.setup()
    render(<Sidebar />)

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
    const view = render(<Sidebar />)

    await user.click(screen.getByRole("button", { name: "Expand sidebar" }))
    expect(screen.getByText("Explore")).toBeInTheDocument()

    // Simulate navigation: pathname changes, component re-renders in place.
    routerMock.pathname = "/explore"
    view.rerender(<Sidebar />)

    expect(screen.getByText("Explore")).toBeInTheDocument()
    expect(screen.getByTestId("app-sidebar")).toHaveStyle({
      width: `${LAYOUT.sidebarExpandedWidth}px`,
    })
  })

  it("opens the profile dropdown with all account options", async () => {
    const user = userEvent.setup()
    render(<Sidebar />)

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
    render(<Sidebar />)

    await user.click(screen.getByRole("button", { name: "Account" }))

    expect(await screen.findByRole("dialog")).toBeInTheDocument()
  })
})
