import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ExplorePage from "@/app/explore/page"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function stubFetch(...responses: (() => Response)[]) {
  const fetchMock = vi.fn()
  for (const response of responses)
    fetchMock.mockImplementationOnce(async () => response())
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

describe("ExplorePage", () => {
  it("renders Genre Channels and New Releases only (AC1)", async () => {
    stubFetch(() => discoverPage([]))
    render(<ExplorePage />)
    const headings = screen.getAllByRole("heading", { level: 2 })
    expect(headings.map((h) => h.textContent)).toEqual([
      "Genre Channels",
      "New Releases",
    ])
    await screen.findByText("No public songs yet.")
  })

  it("genre tiles link to genre-filtered search views (AC3)", async () => {
    stubFetch(() => discoverPage([]))
    render(<ExplorePage />)
    const tiles = screen.getAllByTestId("genre-tile")
    expect(tiles[0]).toHaveAttribute("href", "/search?style=rock")
    expect(
      tiles.every((t) => t.getAttribute("href")?.startsWith("/search?style="))
    ).toBe(true)
    await screen.findByText("No public songs yet.")
  })

  it("loads the newest public clips into New Releases, each linking to its song (AC5)", async () => {
    const fetchMock = stubFetch(() =>
      discoverPage([
        makeClip({ id: "n1", title: "Fresh" }),
        makeClip({ id: "n2" }),
      ])
    )
    render(<ExplorePage />)
    expect(screen.getByText("Loading new releases…")).toBeInTheDocument()

    const cards = await screen.findAllByTestId("explore-clip-card")
    expect(cards.map((c) => c.getAttribute("href"))).toEqual([
      "/song/n1",
      "/song/n2",
    ])
    expect(clipRequests(fetchMock)).toEqual([{ sort: "newest", limit: "12" }])
  })

  it("shows an error with a retry that refetches", async () => {
    stubFetch(
      () => new Response("{}", { status: 502 }),
      () => discoverPage([makeClip({ id: "n1" })])
    )
    render(<ExplorePage />)
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load new releases."
    )

    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findAllByTestId("explore-clip-card")).toHaveLength(1)
  })
})
