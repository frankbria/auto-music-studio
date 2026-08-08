import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { BillingSettings } from "@/components/settings/BillingSettings"

// US-26.3 AC1 + AC4 on the surface a musician actually reaches. The page is the
// destination UPGRADE_URL has pointed at since US-26.2, when it was still a 404.

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function subscription(overrides: Record<string, unknown> = {}) {
  return {
    tier: "free",
    status: null,
    current_period_end: null,
    cancel_at_period_end: false,
    billing_enabled: true,
    ...overrides,
  }
}

/** Route each billing call to a canned response by path. */
function stubApi(routes: Record<string, unknown>, status = 200) {
  // `init` is declared so callers can assert on the request body — the pack-id test
  // needs it, and without the parameter the mock's tuple type has no index 1.
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void init
    const url = String(input)
    const key = Object.keys(routes).find((k) => url.includes(k))
    return Promise.resolve(
      key
        ? jsonRes(routes[key], status)
        : jsonRes({ detail: "not stubbed" }, 404)
    )
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  // stubGlobal survives restoreAllMocks — without this the next file inherits it.
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("BillingSettings", () => {
  it("shows the free plan with an upgrade CTA", async () => {
    stubApi({ subscription: subscription(), history: { entries: [] } })
    render(<BillingSettings accessToken="tok" />)

    expect(await screen.findByText("Free")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /upgrade to pro/i })
    ).toBeInTheDocument()
  })

  it("sends the musician to Stripe when they upgrade (AC1)", async () => {
    stubApi({
      subscription: subscription(),
      history: { entries: [] },
      checkout: { url: "https://checkout.stripe.com/c/pay/test" },
    })
    // jsdom throws on a real navigation assignment; capture it instead.
    const location = { href: "" }
    vi.stubGlobal("location", location)

    render(<BillingSettings accessToken="tok" />)
    await userEvent.click(
      await screen.findByRole("button", { name: /upgrade to pro/i })
    )

    await waitFor(() =>
      expect(location.href).toBe("https://checkout.stripe.com/c/pay/test")
    )
  })

  it("offers portal management instead of checkout once Pro", async () => {
    stubApi({
      subscription: subscription({ tier: "pro", status: "active" }),
      history: { entries: [] },
    })
    render(<BillingSettings accessToken="tok" />)

    expect(
      await screen.findByRole("button", { name: /manage subscription/i })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /upgrade to pro/i })
    ).not.toBeInTheDocument()
  })

  it("tells a cancelling subscriber when access actually ends (AC2)", async () => {
    // The most important sentence on the page — someone who has cancelled must not
    // think they have already lost what they paid for.
    stubApi({
      subscription: subscription({
        tier: "pro",
        status: "active",
        cancel_at_period_end: true,
        current_period_end: "2026-09-01T00:00:00Z",
      }),
      history: { entries: [] },
    })
    render(<BillingSettings accessToken="tok" />)

    expect(
      await screen.findByText(/Pro access continues until/i)
    ).toBeInTheDocument()
  })

  it("warns about a failed payment without implying access is gone (AC3)", async () => {
    stubApi({
      subscription: subscription({ tier: "pro", status: "past_due" }),
      history: { entries: [] },
    })
    render(<BillingSettings accessToken="tok" />)

    expect(
      await screen.findByText(/could not take your last payment/i)
    ).toBeInTheDocument()
    // Still Pro — the grace period is the point.
    expect(screen.getByText("Pro")).toBeInTheDocument()
  })

  it("lists past charges with dates and amounts (AC4)", async () => {
    stubApi({
      subscription: subscription({ tier: "pro", status: "active" }),
      history: {
        entries: [
          {
            id: "b1",
            event_type: "invoice.paid",
            amount: 12,
            currency: "usd",
            status: "paid",
            description: "Pro monthly",
            invoice_url: "https://stripe.example/i/1",
            created_at: "2026-08-01T00:00:00Z",
          },
        ],
      },
    })
    render(<BillingSettings accessToken="tok" />)

    expect(await screen.findByText("Pro monthly")).toBeInTheDocument()
    expect(screen.getByText("$12.00")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /invoice/i })).toHaveAttribute(
      "href",
      "https://stripe.example/i/1"
    )
  })

  it("hides the upgrade CTA where billing is not configured", async () => {
    // A deployment with no Stripe must not offer a button that 503s.
    stubApi({
      subscription: subscription({ billing_enabled: false }),
      history: { entries: [] },
    })
    render(<BillingSettings accessToken="tok" />)

    expect(
      await screen.findByText(/not configured on this deployment/i)
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /upgrade to pro/i })
    ).not.toBeInTheDocument()
  })

  it("surfaces a checkout failure instead of navigating nowhere", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("checkout")) {
        return Promise.resolve(
          jsonRes({ detail: "Stripe is not configured." }, 503)
        )
      }
      if (url.includes("subscription"))
        return Promise.resolve(jsonRes(subscription()))
      return Promise.resolve(jsonRes({ entries: [] }))
    })
    vi.stubGlobal("fetch", fetchMock)
    const location = { href: "" }
    vi.stubGlobal("location", location)

    render(<BillingSettings accessToken="tok" />)
    await userEvent.click(
      await screen.findByRole("button", { name: /upgrade to pro/i })
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /not configured/i
    )
    expect(location.href).toBe("")
    // The button comes back, or a transient failure would strand the page.
    expect(
      screen.getByRole("button", { name: /upgrade to pro/i })
    ).toBeEnabled()
  })
})

describe("BillingSettings — credit packs (US-26.4)", () => {
  const PACKS = {
    packs: [
      { id: "50", credits: 50, price: 5, currency: "usd" },
      { id: "100", credits: 100, price: 9, currency: "usd" },
      { id: "250", credits: 250, price: 20, currency: "usd" },
    ],
  }

  it("offers the packs with their prices (AC1 entry point)", async () => {
    stubApi({
      subscription: subscription(),
      history: { entries: [] },
      packs: PACKS,
    })
    render(<BillingSettings accessToken="tok" />)

    expect(await screen.findByText("Buy credits")).toBeInTheDocument()
    expect(screen.getByText("50 credits")).toBeInTheDocument()
    expect(screen.getByText("$5.00")).toBeInTheDocument()
    expect(screen.getByText("$20.00")).toBeInTheDocument()
  })

  it("sends the musician to Stripe for the pack they picked", async () => {
    const fetchMock = stubApi({
      subscription: subscription(),
      history: { entries: [] },
      packs: PACKS,
      topup: { url: "https://checkout.stripe.com/c/pay/topup" },
    })
    const location = { href: "" }
    vi.stubGlobal("location", location)

    render(<BillingSettings accessToken="tok" />)
    await userEvent.click(await screen.findByText("100 credits"))

    await waitFor(() =>
      expect(location.href).toBe("https://checkout.stripe.com/c/pay/topup")
    )
    // The pack id must reach the API — buying 100 and being charged for 50 is the
    // failure this asserts against.
    const topupCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("topup")
    )
    expect(JSON.parse(String(topupCall?.[1]?.body))).toEqual({ pack_id: "100" })
  })

  it("offers packs to Pro users too", async () => {
    // A Pro musician who burns 500 credits mid-project needs a top-up more than a free
    // user does, so this sits outside the free-tier branch.
    stubApi({
      subscription: subscription({ tier: "pro", status: "active" }),
      history: { entries: [] },
      packs: PACKS,
    })
    render(<BillingSettings accessToken="tok" />)
    expect(await screen.findByText("Buy credits")).toBeInTheDocument()
  })

  it("hides the pack picker where billing is not configured", async () => {
    stubApi({
      subscription: subscription({ billing_enabled: false }),
      history: { entries: [] },
      packs: PACKS,
    })
    render(<BillingSettings accessToken="tok" />)
    await screen.findByText(/not configured on this deployment/i)
    expect(screen.queryByText("Buy credits")).not.toBeInTheDocument()
  })
})
