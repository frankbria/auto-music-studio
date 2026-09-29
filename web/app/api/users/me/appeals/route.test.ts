import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/users/me/appeals/route"

function req(init: RequestInit = {}, search = ""): NextRequest {
  return new Request(
    `http://localhost/api/users/me/appeals${search}`,
    init
  ) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("GET /api/users/me/appeals", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req())
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and passes the appeals through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ appeals: [{ id: "a1" }] }), {
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req({ headers: { authorization: "Bearer tok" } }))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ appeals: [{ id: "a1" }] })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/users/me/appeals")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("forwards the page query to the backend (#543)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ appeals: [], next_cursor: null }), {
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req({ headers: { authorization: "Bearer tok" } }, "?limit=2&cursor=abc")
    )

    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/api\/v1\/users\/me\/appeals\?limit=2&cursor=abc$/
    )
  })
})
