import { afterEach, describe, expect, it, vi } from "vitest"

import {
  CreditsError,
  fetchBalance,
  formatCredits,
  parseInsufficientCredits,
} from "@/lib/credits"

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

describe("fetchBalance", () => {
  it("sends the bearer token and returns the balance", async () => {
    const fetchMock = stubFetch({
      balance: 42.5,
      tier: "free",
      upgrade_url: "/settings/billing",
    })

    const result = await fetchBalance("tok")

    expect(result.balance).toBe(42.5)
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/credits/balance",
      expect.objectContaining({
        headers: { authorization: "Bearer tok" },
        cache: "no-store",
      })
    )
  })

  it("throws with the server's message and status on failure", async () => {
    stubFetch({ detail: "Not authenticated." }, 401)

    await expect(fetchBalance("tok")).rejects.toMatchObject({
      name: "CreditsError",
      status: 401,
      message: "Not authenticated.",
    })
  })

  it("falls back to a readable message when the body has none", async () => {
    stubFetch({}, 502)

    await expect(fetchBalance("tok")).rejects.toBeInstanceOf(CreditsError)
  })
})

describe("parseInsufficientCredits", () => {
  const payload = {
    error: "insufficient_credits",
    balance: 0.5,
    required: 1,
    message: "This action needs 1 credits and you have 0.5.",
    upgrade_url: "/settings/billing",
  }

  it("reads the FastAPI-nested shape", () => {
    expect(parseInsufficientCredits({ detail: payload })).toMatchObject({
      required: 1,
      balance: 0.5,
      upgrade_url: "/settings/billing",
    })
  })

  it("reads a bare body too", () => {
    // Older hand-rolled 402s used the same keys without the wrapper.
    expect(parseInsufficientCredits(payload)?.required).toBe(1)
  })

  it("returns null for anything that is not an insufficient-credits body", () => {
    expect(parseInsufficientCredits({ detail: "Not found." })).toBeNull()
    expect(parseInsufficientCredits(null)).toBeNull()
    expect(parseInsufficientCredits({ detail: { error: "other" } })).toBeNull()
  })

  it("still yields a usable message and upgrade target when the server omits them", () => {
    // The point of the type is that the UI always has somewhere to send the user.
    const parsed = parseInsufficientCredits({
      detail: { error: "insufficient_credits", balance: 0, required: 2 },
    })

    expect(parsed?.message).toContain("2")
    expect(parsed?.upgrade_url).toBe("/settings/billing")
  })
})

describe("formatCredits", () => {
  it("keeps whole numbers whole", () => {
    expect(formatCredits(10)).toBe("10")
    expect(formatCredits(0)).toBe("0")
  })

  it("shows one decimal for half credits", () => {
    // remaster costs 0.5, so halves are real balances, not rounding noise.
    expect(formatCredits(9.5)).toBe("9.5")
  })
})
