import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import ExplorePage from "@/app/explore/page"

describe("ExplorePage", () => {
  it("renders all five discovery sections (AC1)", () => {
    render(<ExplorePage />)
    for (const title of [
      "Trending",
      "Genre Channels",
      "Staff Picks",
      "New Releases",
      "Charts",
    ]) {
      expect(
        screen.getByRole("heading", { name: title, level: 2 })
      ).toBeInTheDocument()
    }
  })

  it("genre tiles link to genre-filtered search views (AC3)", () => {
    render(<ExplorePage />)
    const tiles = screen.getAllByTestId("genre-tile")
    expect(tiles.length).toBeGreaterThan(0)
    expect(tiles[0]).toHaveAttribute("href", "/search?style=rock")
    expect(
      tiles.every((t) => t.getAttribute("href")?.startsWith("/search?style="))
    ).toBe(true)
  })

  it("the Charts section numbers its clips (AC4)", () => {
    render(<ExplorePage />)
    const ranks = screen.getAllByTestId("clip-rank")
    expect(ranks[0]).toHaveTextContent("1")
    expect(ranks[1]).toHaveTextContent("2")
  })

  it("every clip card links to a song detail page (AC5)", () => {
    render(<ExplorePage />)
    const cards = screen.getAllByTestId("explore-clip-card")
    expect(cards.length).toBeGreaterThan(0)
    expect(
      cards.every((c) => c.getAttribute("href")?.startsWith("/song/"))
    ).toBe(true)
  })
})
