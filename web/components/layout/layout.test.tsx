import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { LAYOUT } from "@/lib/constants/layout"
import {
  AppShell,
  BottomPlaybar,
  RightPanel,
  Sidebar,
} from "@/components/layout"

describe("layout constants", () => {
  it("define the shell dimensions and a layered z-index scale", () => {
    expect(LAYOUT.sidebarWidth).toBe(64)
    expect(LAYOUT.playbarHeight).toBe(72)
    expect(LAYOUT.rightPanelWidth).toBe(320)
    // playbar must sit above the sidebar, which sits above the right panel
    expect(LAYOUT.z.playbar).toBeGreaterThan(LAYOUT.z.sidebar)
    expect(LAYOUT.z.sidebar).toBeGreaterThan(LAYOUT.z.rightPanel)
  })
})

describe("AppShell", () => {
  it("renders children inside the main region on every route", () => {
    render(
      <AppShell>
        <p>route content</p>
      </AppShell>
    )
    const main = screen.getByRole("main")
    expect(main).toHaveTextContent("route content")
  })

  it("always renders the sidebar and the bottom playbar", () => {
    render(<AppShell>x</AppShell>)
    expect(screen.getByTestId("app-sidebar")).toBeInTheDocument()
    expect(screen.getByTestId("app-playbar")).toBeInTheDocument()
  })

  it("reserves bottom space for the fixed playbar so content is not hidden", () => {
    render(<AppShell>x</AppShell>)
    expect(screen.getByTestId("app-shell")).toHaveStyle({
      paddingBottom: `${LAYOUT.playbarHeight}px`,
    })
  })

  it("only renders the right panel when rightPanel content is provided", () => {
    const { rerender } = render(<AppShell>x</AppShell>)
    expect(screen.queryByTestId("app-right-panel")).not.toBeInTheDocument()

    rerender(<AppShell rightPanel={<span>context</span>}>x</AppShell>)
    expect(screen.getByTestId("app-right-panel")).toBeInTheDocument()
  })
})

describe("Sidebar", () => {
  it("is a fixed-width icon bar above main content", () => {
    render(<Sidebar />)
    const el = screen.getByTestId("app-sidebar")
    expect(el).toHaveStyle({ width: `${LAYOUT.sidebarWidth}px` })
    expect(el.className).toContain(`z-${LAYOUT.z.sidebar}`)
  })
})

describe("RightPanel", () => {
  it("renders its children and hides below the lg breakpoint", () => {
    render(<RightPanel>contextual content area</RightPanel>)
    const el = screen.getByTestId("app-right-panel")
    expect(el).toHaveTextContent("contextual content area")
    // hidden by default, shown only at lg and up
    expect(el.className).toContain("hidden")
    expect(el.className).toContain("lg:flex")
  })
})

describe("BottomPlaybar", () => {
  it("is fixed to the viewport bottom above all other zones", () => {
    render(<BottomPlaybar />)
    const el = screen.getByTestId("app-playbar")
    expect(el.className).toContain("fixed")
    expect(el.className).toContain("bottom-0")
    expect(el.className).toContain(`z-${LAYOUT.z.playbar}`)
    expect(el).toHaveStyle({ height: `${LAYOUT.playbarHeight}px` })
  })
})
