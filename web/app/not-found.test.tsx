import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import NotFound from "@/app/not-found"

describe("404 page (#339)", () => {
  it("says the page doesn't exist and links home and to search", () => {
    render(<NotFound />)

    expect(
      screen.getByRole("heading", { name: "Page not found" })
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Go home" })).toHaveAttribute(
      "href",
      "/"
    )
    expect(screen.getByRole("link", { name: "Search songs" })).toHaveAttribute(
      "href",
      "/search"
    )
  })
})
