import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/mastering/jobs/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request(
    "http://localhost/api/mastering/jobs?clip_id=c%201",
    init
  ) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("GET /api/mastering/jobs", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req())
    expect(res.status).toBe(401)
  })

  it("forwards the clip filter and Bearer token, passing the list through", async () => {
    const jobs = [{ job_id: "j1", status: "queued", is_approved: false }]
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ jobs }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req({ headers: { authorization: "Bearer tok" } }))

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ jobs })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/v1\/mastering\/jobs\?clip_id=c(%20|\+)1$/)
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
