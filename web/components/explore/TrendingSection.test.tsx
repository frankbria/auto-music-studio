import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { TrendingSection } from "@/components/explore/TrendingSection"

// First clip's link target, used to detect that the 24h/7d toggle reorders.
function firstCardHref(): string | null {
  return screen.getAllByTestId("explore-clip-card")[0].getAttribute("href")
}

describe("TrendingSection", () => {
  it("re-ranks the row when switching 24h ↔ 7d (AC2)", () => {
    render(<TrendingSection />)

    // Defaults to 24h (weights likes+shares).
    const toggle24h = screen.getByRole("button", { name: "24h" })
    expect(toggle24h).toHaveAttribute("aria-pressed", "true")
    const href24h = firstCardHref()

    fireEvent.click(screen.getByRole("button", { name: "7d" }))
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    // 7d weights plays — a different clip leads the row.
    expect(firstCardHref()).not.toBe(href24h)
  })
})
