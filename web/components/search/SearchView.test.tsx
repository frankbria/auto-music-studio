import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SearchView } from "@/components/search/SearchView"
import { GENRES } from "@/lib/explore"
import { DEFAULT_SEARCH, type SearchParams } from "@/lib/search"
import { makeClip } from "@/test/clip-factory"
import {
  clipRequests,
  discoverPage,
  stubDiscoverFetch,
  stubViewerAwareDiscover,
} from "@/test/discover-api"
import { SignedIn } from "@/test/signed-in"

const params = (over: Partial<SearchParams> = {}): SearchParams => ({
  ...DEFAULT_SEARCH,
  ...over,
})

const cards = () => screen.queryAllByTestId("explore-clip-card")
const hrefs = () => cards().map((c) => c.getAttribute("href"))

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("SearchView", () => {
  it("shows suggestions, and searches nothing, when there is no query or filter (AC5)", async () => {
    const fetchMock = stubDiscoverFetch(() => discoverPage([]))
    render(<SearchView params={params()} onChange={vi.fn()} />)
    expect(screen.getByTestId("search-empty")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "lofi" })).toBeInTheDocument()
    await act(async () => {})
    expect(clipRequests(fetchMock)).toEqual([])
  })

  it("picks a genre suggestion from the empty state", async () => {
    stubDiscoverFetch(() => discoverPage([]))
    const onChange = vi.fn()
    render(<SearchView params={params()} onChange={onChange} />)
    const empty = screen.getByTestId("search-empty")
    await userEvent.click(within(empty).getByRole("button", { name: "Rock" }))
    expect(onChange).toHaveBeenCalledWith({ style: "rock" })
  })

  it("shows a loader, then the results and the API's total (AC1)", async () => {
    const fetchMock = stubDiscoverFetch(() =>
      discoverPage([makeClip({ id: "neon" })], "c2", 12)
    )
    render(<SearchView params={params({ q: "neon" })} onChange={vi.fn()} />)
    expect(screen.getByTestId("search-loading")).toBeInTheDocument()

    expect(await screen.findByText("12 results")).toBeInTheDocument()
    expect(hrefs()).toEqual(["/song/neon"])
    expect(clipRequests(fetchMock)).toEqual([{ q: "neon", sort: "relevance" }])
  })

  it("sends the BPM range and other filters to the API (AC2)", async () => {
    const fetchMock = stubDiscoverFetch(() => discoverPage([makeClip()]))
    render(
      <SearchView
        params={params({
          bpmMin: 120,
          bpmMax: 140,
          style: "rock",
          sort: "newest",
        })}
        onChange={vi.fn()}
      />
    )
    await screen.findByText("1 result")
    expect(clipRequests(fetchMock)).toEqual([
      { style: "rock", bpm_min: "120", bpm_max: "140", sort: "newest" },
    ])
  })

  it("shows the no-results state when nothing matches", async () => {
    stubDiscoverFetch(() => discoverPage([]))
    render(<SearchView params={params({ q: "zzzz" })} onChange={vi.fn()} />)
    expect(await screen.findByTestId("search-no-results")).toBeInTheDocument()
    expect(cards()).toHaveLength(0)
  })

  it("shows an error with a retry that searches again", async () => {
    let fail = true
    const fetchMock = stubDiscoverFetch(() =>
      fail ? new Response("{}", { status: 429 }) : discoverPage([makeClip()])
    )
    render(<SearchView params={params({ q: "neon" })} onChange={vi.fn()} />)
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Search is unavailable right now."
    )

    fail = false
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("1 result")).toBeInTheDocument()
    expect(clipRequests(fetchMock)).toHaveLength(2)
  })

  it("appends the next page on Load more, and hides it on the last page", async () => {
    const fetchMock = stubDiscoverFetch((url) =>
      url.includes("cursor=c2")
        ? discoverPage([makeClip({ id: "b" })], null, 2)
        : discoverPage([makeClip({ id: "a" })], "c2", 2)
    )
    render(<SearchView params={params({ q: "x" })} onChange={vi.fn()} />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more" })
    )

    expect(await screen.findAllByTestId("explore-clip-card")).toHaveLength(2)
    expect(hrefs()).toEqual(["/song/a", "/song/b"])
    expect(clipRequests(fetchMock)[1]).toEqual({
      q: "x",
      sort: "relevance",
      cursor: "c2",
    })
    expect(
      screen.queryByRole("button", { name: "Load more" })
    ).not.toBeInTheDocument()
  })

  it("keeps the results and reports it when Load more fails", async () => {
    stubDiscoverFetch((url) =>
      url.includes("cursor=c2")
        ? new Response("{}", { status: 502 })
        : discoverPage([makeClip({ id: "a" })], "c2", 2)
    )
    render(<SearchView params={params({ q: "x" })} onChange={vi.fn()} />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more" })
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load more results."
    )
    expect(hrefs()).toEqual(["/song/a"])
    expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled()
  })

  it("ignores a response for a search that is no longer current", async () => {
    let releaseOld = () => {}
    stubDiscoverFetch((url) =>
      url.includes("q=old")
        ? new Promise((resolve) => {
            releaseOld = () => resolve(discoverPage([makeClip({ id: "old" })]))
          })
        : discoverPage([makeClip({ id: "new" })])
    )
    const { rerender } = render(
      <SearchView params={params({ q: "old" })} onChange={vi.fn()} />
    )
    rerender(<SearchView params={params({ q: "new" })} onChange={vi.fn()} />)
    await screen.findByText("1 result")
    await act(async () => releaseOld())

    expect(hrefs()).toEqual(["/song/new"])
  })

  it("offers the API's keys as filter options", async () => {
    stubDiscoverFetch(() => discoverPage([]), {
      keys: ["F# minor"],
      models: [],
    })
    render(<SearchView params={params()} onChange={vi.fn()} />)
    await act(async () => {})
    await userEvent.click(screen.getByRole("button", { name: "Key: Any" }))
    expect(
      await screen.findByRole("menuitemradio", { name: "F# minor" })
    ).toBeInTheDocument()
  })

  it("offers only Relevance and Newest, and emits the chosen sort (AC3)", async () => {
    stubDiscoverFetch(() => discoverPage([]))
    const onChange = vi.fn()
    render(<SearchView params={params({ q: "a" })} onChange={onChange} />)
    await userEvent.click(screen.getByRole("button", { name: /sort by/i }))
    expect(
      screen.getAllByRole("menuitemradio").map((item) => item.textContent)
    ).toEqual(["Relevance", "Newest"])
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Newest" }))
    expect(onChange).toHaveBeenCalledWith({ sort: "newest" })
  })

  it("debounces the search box before committing the query", () => {
    stubDiscoverFetch(() => discoverPage([]))
    // fireEvent (not userEvent) so no internal delays fight the fake timers.
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<SearchView params={params()} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText("Search songs"), {
      target: { value: "jazz" },
    })
    expect(onChange).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(300))
    expect(onChange).toHaveBeenCalledWith({ q: "jazz" })
  })
})

describe("SearchView viewer ownership (#653)", () => {
  it("sends the viewer's token and offers Report only on someone else's clip", async () => {
    const fetchMock = stubViewerAwareDiscover(
      [
        makeClip({ id: "mine", title: "Mine" }),
        makeClip({ id: "theirs", title: "Theirs" }),
      ],
      "mine"
    )
    render(
      <SignedIn>
        <SearchView params={params({ q: "night" })} onChange={vi.fn()} />
      </SignedIn>
    )

    await screen.findByText("Theirs")
    expect(screen.getAllByRole("button", { name: /report/i })).toHaveLength(1)
    const search = fetchMock.mock.calls.find(([url]) =>
      String(url).startsWith("/api/discover/clips")
    )
    expect(new Headers(search?.[1]?.headers).get("authorization")).toBe(
      "Bearer tok"
    )
  })
})

describe("SearchView polish (#657)", () => {
  it("drops a Load more answer when its search was replaced and restored meanwhile", async () => {
    let answerMore: (r: Response) => void = () => {}
    stubDiscoverFetch((url) => {
      if (url.includes("cursor=c2")) {
        return new Promise<Response>((resolve) => (answerMore = resolve))
      }
      // Page 1 of "a" changes between the two loads: a newer clip landed.
      const restored = url.includes("q=a") && pageOneLoads++ > 0
      return url.includes("q=a")
        ? discoverPage([makeClip({ id: restored ? "new" : "a1" })], "c2", 3)
        : discoverPage([makeClip({ id: "b1" })], null, 1)
    })
    let pageOneLoads = 0
    const { rerender } = render(
      <SearchView params={params({ q: "a" })} onChange={vi.fn()} />
    )
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more" })
    )
    rerender(<SearchView params={params({ q: "b" })} onChange={vi.fn()} />)
    await waitFor(() => expect(hrefs()).toEqual(["/song/b1"]))
    rerender(<SearchView params={params({ q: "a" })} onChange={vi.fn()} />)
    await waitFor(() => expect(hrefs()).toEqual(["/song/new"]))

    await act(async () => {
      answerMore(discoverPage([makeClip({ id: "a2" })], null, 3))
    })

    expect(hrefs()).toEqual(["/song/new"])
  })

  it("links the R&B tile to the style generated tags use", () => {
    expect(GENRES.find((g) => g.name === "R&B")?.slug).toBe("r&b")
  })
})
