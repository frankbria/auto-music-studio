import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/releases/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request(
    "http://localhost/api/releases",
    init
  ) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("GET /api/releases", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req())
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and passes the list through", async () => {
    const body = { releases: [{ id: "r1" }], total: 1 }
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req({ headers: { authorization: "Bearer tok" } }))

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual(body)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/v1\/releases$/)
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")))
    const res = await GET(req({ headers: { authorization: "Bearer tok" } }))
    expect(res.status).toBe(502)
  })
})
