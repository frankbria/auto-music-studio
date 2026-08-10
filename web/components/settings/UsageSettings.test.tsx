import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { UsageSettings } from "@/components/settings/UsageSettings"
import type { UsageSummary } from "@/lib/usage"

function summary(overrides: Partial<UsageSummary> = {}): UsageSummary {
  return {
    tier: "pro",
    monthly_credits: 420,
    purchased_credits: 80,
    total_credits: 500,
    reset_at: "2026-09-01T00:00:00Z",
    days_until_reset: 12,
    window_days: 30,
    daily: [
      { date: "2026-08-01", credits: 4 },
      { date: "2026-08-02", credits: 0 },
      { date: "2026-08-03", credits: 6 },
    ],
    categories: [
      { category: "generation", credits: 7 },
      { category: "mastering", credits: 3 },
    ],
    history: [
      {
        created_at: "2026-08-03T09:00:00Z",
        action_type: "mastering",
        category: "mastering",
        amount: -3,
        balance_after: 497,
        job_id: "j1",
        clip_title: "Midnight Drive",
      },
      {
        created_at: "2026-08-01T09:00:00Z",
        action_type: "monthly_reset",
        category: "grant",
        amount: 500,
        balance_after: 503,
        job_id: "",
        clip_title: null,
      },
    ],
    ...overrides,
  }
}

function stubUsage(body: unknown, status = 200) {
  // A fresh Response per call: a Response body can only be read once, so a shared one
  // makes the second window's fetch look like a malformed payload.
  const fetchMock = vi
    .fn()
    .mockImplementation(
      async () => new Response(JSON.stringify(body), { status })
    )
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  // stubGlobal survives restoreAllMocks — without this the next file inherits it.
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("UsageSettings", () => {
  it("shows the balance split, tier and reset countdown", async () => {
    stubUsage(summary())

    render(<UsageSettings accessToken="tok" />)

    expect(await screen.findByText("500")).toBeInTheDocument()
    expect(screen.getByText(/420 monthly/i)).toBeInTheDocument()
    expect(screen.getByText(/80 purchased/i)).toBeInTheDocument()
    expect(screen.getByText(/12 days/i)).toBeInTheDocument()
    expect(screen.getByText("Pro")).toBeInTheDocument()
  })

  it("charts daily consumption over the window", async () => {
    stubUsage(summary())

    render(<UsageSettings accessToken="tok" />)

    const chart = await screen.findByRole("img", {
      name: /credits used per day/i,
    })
    // One bar per day including the quiet ones, or the x-axis lies about its span.
    expect(chart.querySelectorAll("rect")).toHaveLength(3)
  })

  it("breaks usage down by category with readable labels", async () => {
    stubUsage(summary())

    render(<UsageSettings accessToken="tok" />)

    // Scoped: the same action names appear again in the history table below.
    const breakdown = within(await screen.findByTestId("category-breakdown"))
    expect(breakdown.getByText("Generation")).toBeInTheDocument()
    expect(breakdown.getByText("Mastering")).toBeInTheDocument()
  })

  it("draws no bar for a category that nets credit back", async () => {
    // A refund inside the window whose charge fell outside it nets negative. A negative
    // CSS width is invalid, so the browser drops it and the bar renders full-width —
    // showing the biggest spend of the month where credit was actually returned.
    stubUsage(
      summary({
        categories: [
          { category: "generation", credits: 7 },
          { category: "mastering", credits: -4 },
        ],
      })
    )

    render(<UsageSettings accessToken="tok" />)

    const breakdown = await screen.findByTestId("category-breakdown")
    const bars =
      breakdown.querySelectorAll<HTMLElement>('[data-testid="category-bar"]')
    expect(bars[0].style.width).toBe("100%")
    expect(bars[1].style.width).toBe("0%")
    expect(breakdown).toHaveTextContent("-4 credits")
  })

  it("lists every credit movement, including grants", async () => {
    stubUsage(summary())

    render(<UsageSettings accessToken="tok" />)

    expect(await screen.findByText("Midnight Drive")).toBeInTheDocument()
    // A grant is a credit, not a charge — it must read as one.
    expect(screen.getByText("+500")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
  })

  it("exports the history as a CSV download", async () => {
    stubUsage(summary())
    const createUrl = vi.fn().mockReturnValue("blob:test")
    URL.createObjectURL = createUrl
    URL.revokeObjectURL = vi.fn()
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {})

    render(<UsageSettings accessToken="tok" />)
    await userEvent.click(await screen.findByRole("button", { name: /csv/i }))

    expect(click).toHaveBeenCalledOnce()
    expect(createUrl).toHaveBeenCalledOnce()
  })

  it("re-reads the window when a different range is chosen", async () => {
    const fetchMock = stubUsage(summary())

    render(<UsageSettings accessToken="tok" />)
    await screen.findByText("500")
    await userEvent.click(screen.getByRole("button", { name: "7 days" }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/credits/usage?days=7",
        expect.anything()
      )
    )
  })

  it("says so when there is nothing to show yet", async () => {
    stubUsage(summary({ categories: [], history: [] }))

    render(<UsageSettings accessToken="tok" />)

    expect(await screen.findByText(/no credits used/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /csv/i })
    ).toBeDisabled()
  })

  it("reports a failed load instead of rendering an empty dashboard", async () => {
    stubUsage({ detail: "Credit service is unavailable." }, 502)

    render(<UsageSettings accessToken="tok" />)

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /credit service is unavailable/i
    )
  })
})
