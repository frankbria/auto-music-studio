import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import HomePage from "@/app/page"

describe("home page (#722)", () => {
  it("says what the product is and starts the visitor creating", () => {
    render(<HomePage />)

    expect(
      screen.getByRole("heading", { level: 1, name: "Auto Music Studio" })
    ).toBeInTheDocument()
    // Signed-out visitors reach /login?from=/create through the proxy gate on /create.
    expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute(
      "href",
      "/create"
    )
    expect(screen.getByRole("link", { name: "Explore music" })).toHaveAttribute(
      "href",
      "/explore"
    )
    expect(screen.queryByText(/placeholder|scaffold/i)).not.toBeInTheDocument()
  })
})
