import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/jobs/[jobId]/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request(
    "http://localhost/api/jobs/j1",
    init
  ) as unknown as NextRequest
}

const ctx = (jobId = "j1") => ({ params: Promise.resolve({ jobId }) })

afterEach(() => vi.restoreAllMocks())

describe("GET /api/jobs/[jobId]", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req(), ctx())
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and passes the job status through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            job_id: "j1",
            status: "completed",
            clip_ids: ["c1", "c2"],
          }),
          { status: 200 }
        )
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx()
    )
    expect(res.status).toBe(200)
    expect(await res.json()).toMatchObject({
      status: "completed",
      clip_ids: ["c1", "c2"],
    })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/jobs/j1/status")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("encodes the job id into the upstream URL", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req({ headers: { authorization: "Bearer tok" } }), ctx("a/b"))
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/jobs/a%2Fb/status")
  })

  it("returns a controlled 502 when the upstream fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx()
    )
    expect(res.status).toBe(502)
  })

  it("surfaces a 404 verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "Job not found." }), {
            status: 404,
          })
        )
    )
    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx()
    )
    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: "Job not found." })
  })
})
