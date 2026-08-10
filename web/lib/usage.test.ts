import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildUsageCsv,
  fetchUsage,
  formatCategory,
  type UsageRow,
  type UsageSummary,
} from "@/lib/usage"

function row(overrides: Partial<UsageRow> = {}): UsageRow {
  return {
    created_at: "2026-08-01T12:00:00Z",
    action_type: "song",
    category: "generation",
    amount: -1.5,
    balance_after: 48.5,
    job_id: "abc",
    clip_title: null,
    ...overrides,
  }
}

function summary(overrides: Partial<UsageSummary> = {}): UsageSummary {
  return {
    tier: "free",
    monthly_credits: 48.5,
    purchased_credits: 0,
    total_credits: 48.5,
    reset_at: "2026-09-01T00:00:00Z",
    days_until_reset: 21,
    window_days: 30,
    daily: [],
    categories: [],
    history: [row()],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("buildUsageCsv", () => {
  it("writes a header and one line per movement", () => {
    const csv = buildUsageCsv(summary())
    const lines = csv.trim().split("\n")

    expect(lines[0]).toBe("date,action,category,clip,credits,balance_after")
    expect(lines).toHaveLength(2)
    // Credits read as spent, matching the sign convention on screen — a charge is a
    // positive number of credits used, not a negative balance movement.
    expect(lines[1]).toBe("2026-08-01T12:00:00Z,song,generation,,1.5,48.5")
  })

  it("shows a refund as negative credits used", () => {
    const csv = buildUsageCsv(
      summary({ history: [row({ action_type: "song_refund", amount: 1.5 })] })
    )
    expect(csv.trim().split("\n")[1]).toContain(",-1.5,")
  })

  it("quotes and escapes titles containing commas or quotes", () => {
    // A clip called `Hey, "You"` would otherwise shift every later column by one.
    const csv = buildUsageCsv(
      summary({ history: [row({ clip_title: 'Hey, "You"' })] })
    )
    expect(csv).toContain('"Hey, ""You"""')
  })

  it("still produces a header when there is nothing to export", () => {
    expect(buildUsageCsv(summary({ history: [] })).trim()).toBe(
      "date,action,category,clip,credits,balance_after"
    )
  })
})

describe("formatCategory", () => {
  it("titles known categories and falls back to the raw value", () => {
    expect(formatCategory("generation")).toBe("Generation")
    expect(formatCategory("voice")).toBe("Voice training")
    expect(formatCategory("wat")).toBe("wat")
  })
})

describe("fetchUsage", () => {
  it("requests the window with a bearer token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(summary()), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const result = await fetchUsage("tok", 7)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/credits/usage?days=7",
      expect.objectContaining({
        headers: { authorization: "Bearer tok" },
        cache: "no-store",
      })
    )
    expect(result.tier).toBe("free")
  })

  it("throws the backend detail on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "User not found." }), {
          status: 404,
        })
      )
    )

    await expect(fetchUsage("tok")).rejects.toThrow("User not found.")
  })

  it("rejects a 200 whose payload is not a usage summary", async () => {
    // The dashboard maps over every array in the payload; a truncated body that still
    // came back 200 must surface as an error rather than crash the page.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 200 }))
    )

    await expect(fetchUsage("tok")).rejects.toThrow(/could not load/i)
  })
})
