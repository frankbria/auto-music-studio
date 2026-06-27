import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("GET /api/clips", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req("http://localhost/api/clips"))
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and query string to the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ clips: [], total: 0 }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips?workspace_id=w1&search=lofi&page=2", {
        headers: { authorization: "Bearer tok" },
      })
    )
    expect(res.status).toBe(200)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips")
    expect(url).toContain("workspace_id=w1")
    expect(url).toContain("search=lofi")
    expect(url).toContain("page=2")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("passes the backend status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), { status: 422 })
      )
    )
    const res = await GET(
      req("http://localhost/api/clips", {
        headers: { authorization: "Bearer tok" },
      })
    )
    expect(res.status).toBe(422)
  })
})
