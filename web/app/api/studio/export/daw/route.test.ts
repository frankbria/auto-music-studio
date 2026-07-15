import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { POST } from "@/app/api/studio/export/daw/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request("http://localhost/api/studio/export/daw", {
    method: "POST",
    ...init,
  }) as unknown as NextRequest
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/studio/export/daw", () => {
  it("401s without an Authorization header", async () => {
    const res = await POST(req({ body: "{}" }))
    expect(res.status).toBe(401)
  })

  it("forwards the token and body and passes the 202 through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "j2" }), { status: 202 })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req({
        headers: { authorization: "Bearer tok" },
        body: JSON.stringify({ project_name: "Bundle" }),
      })
    )
    expect(res.status).toBe(202)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/studio/export/daw")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await POST(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" })
    )
    expect(res.status).toBe(502)
  })
})
