import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchPlans, startCheckout } from "@/lib/billing"

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("fetchPlans (#695)", () => {
  it("reads the plan catalogue through the same-origin proxy", async () => {
    const pro = {
      plan: "pro",
      monthly_credits: 500,
      prices: { month: 24, year: 228 },
      currency: "usd",
      available: { month: true, year: true },
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ plans: [pro] }))
    vi.stubGlobal("fetch", fetchMock)

    expect(await fetchPlans("tok")).toEqual([pro])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/billing/plans")
    expect((init.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("throws on a failed response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 500)))
    await expect(fetchPlans("tok")).rejects.toThrow(/plans/i)
  })
})

describe("startCheckout (#695)", () => {
  it("posts the chosen plan and interval and returns the Stripe URL", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonRes({ url: "https://checkout.stripe.com/x" }))
    vi.stubGlobal("fetch", fetchMock)

    expect(await startCheckout("tok", "enterprise", "year")).toBe(
      "https://checkout.stripe.com/x"
    )
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/billing/checkout")
    expect(init.method).toBe("POST")
    expect(JSON.parse(String(init.body))).toEqual({
      plan: "enterprise",
      interval: "year",
    })
  })

  it("surfaces the API's 409 detail for an existing subscriber", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "Already subscribed." }, 409))
    )
    await expect(startCheckout("tok", "pro", "month")).rejects.toThrow(
      "Already subscribed."
    )
  })
})
