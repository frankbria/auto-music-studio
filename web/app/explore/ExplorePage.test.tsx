import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ExplorePage from "@/app/explore/page"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

type Responder = () => Response

/** Answer each discovery read by its sort; a sort with a queue answers in order, then repeats its last answer. */
function stubBySort(answers: Partial<Record<string, Responder[]>> = {}) {
  const fetchMock = vi.fn(async (url: string) => {
    const sort = new URL(url, "http://localhost").searchParams.get("sort") ?? ""
    const queue = answers[sort]
    if (!queue?.length) return discoverPage([])
    return (queue.length > 1 ? queue.shift()! : queue[0])()
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function section(title: string): HTMLElement {
  return screen
    .getByRole("heading", { level: 2, name: title })
    .closest("section")!
}

describe("ExplorePage", () => {
  it("shows Trending, Genre Channels, Staff Picks, New Releases and Charts, in that order (AC1, #656)", async () => {
    stubBySort()
    render(<ExplorePage />)
    expect(
      screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)
    ).toEqual([
      "Trending",
      "Genre Channels",
      "Staff Picks",
      "New Releases",
      "Charts",
    ])
    await screen.findByText("Nothing trending yet.")
    await screen.findByText("No staff picks yet.")
    await screen.findByText("No public songs yet.")
    await screen.findByText("No plays yet.")
  })

  it("reads each row from the discovery API in its own order (#656)", async () => {
    const fetchMock = stubBySort()
    render(<ExplorePage />)
    await screen.findByText("No plays yet.")
    expect(
      clipRequests(fetchMock)
        .map((query) => query.sort)
        .sort()
    ).toEqual(["newest", "popular", "staff_picks", "trending_24h"])
  })

  it("genre tiles link to genre-filtered search views (AC3)", async () => {
    stubBySort()
    render(<ExplorePage />)
    const tiles = screen.getAllByTestId("genre-tile")
    expect(tiles[0]).toHaveAttribute("href", "/search?style=rock")
    expect(
      tiles.every((t) => t.getAttribute("href")?.startsWith("/search?style="))
    ).toBe(true)
    await screen.findByText("No public songs yet.")
  })

  it("loads the newest public clips into New Releases, each linking to its song (AC5)", async () => {
    stubBySort({
      newest: [
        () =>
          discoverPage([
            makeClip({ id: "n1", title: "Fresh" }),
            makeClip({ id: "n2" }),
          ]),
      ],
    })
    render(<ExplorePage />)
    expect(screen.getByText("Loading new releases…")).toBeInTheDocument()

    const cards = await within(section("New Releases")).findAllByTestId(
      "explore-clip-card"
    )
    expect(cards.map((c) => c.getAttribute("href"))).toEqual([
      "/song/n1",
      "/song/n2",
    ])
  })

  it("numbers the Charts by position (#656)", async () => {
    stubBySort({
      popular: [
        () =>
          discoverPage([
            makeClip({ id: "top", play_count: 90 }),
            makeClip({ id: "next", play_count: 40 }),
          ]),
      ],
    })
    render(<ExplorePage />)
    const charts = section("Charts")
    await within(charts).findAllByTestId("explore-clip-card")
    expect(
      within(charts)
        .getAllByTestId("clip-rank")
        .map((rank) => rank.textContent)
    ).toEqual(["1", "2"])
    expect(
      within(section("New Releases")).queryByTestId("clip-rank")
    ).toBeNull()
  })

  it("switches Trending between 24h and 7d (AC2, #656)", async () => {
    const fetchMock = stubBySort({
      trending_24h: [() => discoverPage([makeClip({ id: "today" })])],
      trending_7d: [() => discoverPage([makeClip({ id: "this-week" })])],
    })
    render(<ExplorePage />)
    const trending = () => section("Trending")
    expect(
      (await within(trending()).findAllByTestId("explore-clip-card"))[0]
    ).toHaveAttribute("href", "/song/today")

    await userEvent.click(
      within(trending()).getByRole("button", { name: "7d" })
    )

    expect(
      within(trending()).getByRole("button", { name: "7d" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      (await within(trending()).findAllByTestId("explore-clip-card"))[0]
    ).toHaveAttribute("href", "/song/this-week")
    expect(clipRequests(fetchMock).map((query) => query.sort)).toContain(
      "trending_7d"
    )
  })

  it("retries a row that failed while offline when the connection is back (#339)", async () => {
    stubBySort({
      newest: [
        () => new Response("{}", { status: 502 }),
        () => discoverPage([makeClip({ id: "n1" })]),
      ],
    })
    render(<ExplorePage />)
    await within(section("New Releases")).findByRole("alert")

    act(() => {
      window.dispatchEvent(new Event("online"))
    })

    expect(
      await within(section("New Releases")).findAllByTestId("explore-clip-card")
    ).toHaveLength(1)
  })

  it("shows an error with a retry that refetches", async () => {
    stubBySort({
      newest: [
        () => new Response("{}", { status: 502 }),
        () => discoverPage([makeClip({ id: "n1" })]),
      ],
    })
    render(<ExplorePage />)
    expect(
      await within(section("New Releases")).findByRole("alert")
    ).toHaveTextContent("Couldn't load new releases.")

    await userEvent.click(
      within(section("New Releases")).getByRole("button", { name: "Retry" })
    )
    expect(
      await within(section("New Releases")).findAllByTestId("explore-clip-card")
    ).toHaveLength(1)
  })
})
