import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { POST } from "@/app/api/studio/mixdown/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request("http://localhost/api/studio/mixdown", {
    method: "POST",
    ...init,
  }) as unknown as NextRequest
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/studio/mixdown", () => {
  it("401s without an Authorization header", async () => {
    const res = await POST(req({ body: "{}" }))
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and body to the backend and passes the 202 through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "j1", status: "queued" }), {
        status: 202,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req({
        headers: { authorization: "Bearer tok" },
        body: JSON.stringify({ project_name: "Song" }),
      })
    )
    expect(res.status).toBe(202)
    expect(await res.json()).toMatchObject({ job_id: "j1" })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/studio/mixdown")
    expect(opts.method).toBe("POST")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(opts.body).toContain("Song")
  })

  it("passes a 422 validation error through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "bad" }), { status: 422 })
      )
    )
    const res = await POST(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" })
    )
    expect(res.status).toBe(422)
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await POST(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" })
    )
    expect(res.status).toBe(502)
  })
})
