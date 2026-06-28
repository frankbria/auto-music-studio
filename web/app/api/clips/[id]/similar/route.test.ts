import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/[id]/similar/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => vi.restoreAllMocks())

describe("GET /api/clips/[id]/similar", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(
      req("http://localhost/api/clips/c1/similar"),
      ctx("c1")
    )
    expect(res.status).toBe(401)
  })

  it("forwards the token, clip id, and query string", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ clips: [], total: 0, limit: 6 }), {
          status: 200,
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips/c1/similar?scope=mine&limit=6", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(200)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/similar")
    expect(url).toContain("scope=mine")
    expect(url).toContain("limit=6")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("ECONNREFUSED"))
    )
    const res = await GET(
      req("http://localhost/api/clips/c1/similar", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})
