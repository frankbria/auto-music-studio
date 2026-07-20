import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

const { searchParamsRef } = vi.hoisted(() => ({
  searchParamsRef: { current: new URLSearchParams() },
}))

const replace = vi.fn()
// SearchPageClient uses useSearchParams, which the shared setup mock omits
// (see test/router-mock.ts) — provide it here alongside a replace spy.
vi.mock("next/navigation", () => ({
  usePathname: () => "/search",
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParamsRef.current,
}))

import { SearchPageClient } from "@/components/search/SearchPageClient"

afterEach(() => {
  searchParamsRef.current = new URLSearchParams()
  vi.clearAllMocks()
})

describe("SearchPageClient", () => {
  it("initializes search state from the URL (AC4)", () => {
    searchParamsRef.current = new URLSearchParams("q=jazz&sort=newest")
    render(<SearchPageClient />)
    expect(screen.getByLabelText("Search songs")).toHaveValue("jazz")
    expect(screen.getByRole("button", { name: /sort by/i })).toHaveTextContent(
      "Newest"
    )
  })

  it("reflects a filter change back into the URL (AC4)", async () => {
    render(<SearchPageClient />)
    // The URL is the source of truth, so mounting doesn't rewrite it — only a
    // user action does.
    expect(replace).not.toHaveBeenCalled()

    const rockChips = screen.getAllByRole("button", { name: "Rock" })
    await userEvent.click(rockChips[0])
    expect(replace).toHaveBeenLastCalledWith("/search?style=rock", {
      scroll: false,
    })
  })
})
