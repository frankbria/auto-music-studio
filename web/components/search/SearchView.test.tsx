import { act, fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SearchView } from "@/components/search/SearchView"
import { DEFAULT_SEARCH, type SearchParams } from "@/lib/search"

const params = (over: Partial<SearchParams> = {}): SearchParams => ({
  ...DEFAULT_SEARCH,
  ...over,
})

const cards = () => screen.queryAllByTestId("explore-clip-card")
const hrefs = () => cards().map((c) => c.getAttribute("href"))

afterEach(() => vi.useRealTimers())

describe("SearchView", () => {
  it("shows suggestions when there is no query or filter (AC5)", () => {
    render(<SearchView params={params()} onChange={vi.fn()} />)
    expect(screen.getByTestId("search-empty")).toBeInTheDocument()
    expect(cards()).toHaveLength(0)
    expect(screen.getByRole("button", { name: "lofi" })).toBeInTheDocument()
  })

  it("picks a genre suggestion from the empty state", async () => {
    const onChange = vi.fn()
    render(<SearchView params={params()} onChange={onChange} />)
    const empty = screen.getByTestId("search-empty")
    await userEvent.click(within(empty).getByRole("button", { name: "Rock" }))
    expect(onChange).toHaveBeenCalledWith({ style: "rock" })
  })

  it("renders results matching the query (AC1)", () => {
    render(<SearchView params={params({ q: "neon" })} onChange={vi.fn()} />)
    expect(hrefs()).toEqual(["/song/clip-neon"])
    expect(screen.getByText("1 result")).toBeInTheDocument()
  })

  it("narrows results by BPM range (AC2)", () => {
    render(
      <SearchView params={params({ bpmMin: 120, bpmMax: 140 })} onChange={vi.fn()} />
    )
    // In-range clip present; out-of-range clips absent (neon=140, pulse=110,
    // glass=150 — see lib/explore pool).
    expect(hrefs()).toContain("/song/clip-neon")
    expect(hrefs()).not.toContain("/song/clip-pulse")
    expect(hrefs()).not.toContain("/song/clip-glass")
  })

  it("treats a genre deep link (style, no query) as a real search", () => {
    render(<SearchView params={params({ style: "rock" })} onChange={vi.fn()} />)
    expect(screen.queryByTestId("search-empty")).not.toBeInTheDocument()
    expect(hrefs()).toContain("/song/clip-emberr")
  })

  it("shows the no-results state for a query that matches nothing", () => {
    render(<SearchView params={params({ q: "zzzznomatch" })} onChange={vi.fn()} />)
    expect(screen.getByTestId("search-no-results")).toBeInTheDocument()
    expect(cards()).toHaveLength(0)
  })

  it("emits the chosen sort order (AC3)", async () => {
    const onChange = vi.fn()
    render(<SearchView params={params({ q: "a" })} onChange={onChange} />)
    await userEvent.click(screen.getByRole("button", { name: /sort by/i }))
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Most Popular" }))
    expect(onChange).toHaveBeenCalledWith({ sort: "popular" })
  })

  it("debounces the search box before committing the query", () => {
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
