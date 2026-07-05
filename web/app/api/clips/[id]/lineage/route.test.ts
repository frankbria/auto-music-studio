import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/[id]/lineage/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]/lineage", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(
      req("http://localhost/api/clips/c1/lineage"),
      ctx("c1")
    )
    expect(res.status).toBe(401)
  })

  it("forwards the token and clip id to the backend lineage endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ clip_id: "c1", depth_limit: 50, depth_truncated: false, nodes: [] }),
        { status: 200 }
      )
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips/c1/lineage", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(200)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/lineage")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("passes a backend 404 through verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Clip not found." }), { status: 404 })
      )
    )
    const res = await GET(
      req("http://localhost/api/clips/nope/lineage", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("nope")
    )
    expect(res.status).toBe(404)
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await GET(
      req("http://localhost/api/clips/c1/lineage", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})
