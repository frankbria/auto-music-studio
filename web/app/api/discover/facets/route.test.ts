import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/discover/facets/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/discover/facets", () => {
  it("proxies the facets without Authorization or the client query", async () => {
    const facets = { keys: ["A minor"], models: ["m1"] }
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(facets), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/discover/facets?x=1", {
        headers: { authorization: "Bearer tok" },
      })
    )

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/discover\/facets$/)
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.authorization).toBeUndefined()
    expect(res.status).toBe(200)
    await expect(res.json()).resolves.toEqual(facets)
  })

  it("passes a backend error status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 429 }))
    )

    const res = await GET(req("http://localhost/api/discover/facets"))
    expect(res.status).toBe(429)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(req("http://localhost/api/discover/facets"))
    expect(res.status).toBe(502)
  })
})
