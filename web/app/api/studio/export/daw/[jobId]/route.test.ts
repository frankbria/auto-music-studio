import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/studio/export/daw/[jobId]/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request("http://localhost/api/studio/export/daw/j1", {
    ...init,
  }) as unknown as NextRequest
}

const ctx = (jobId: string) => ({ params: Promise.resolve({ jobId }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/studio/export/daw/[jobId]", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req(), ctx("j1"))
    expect(res.status).toBe(401)
  })

  it("streams the ZIP through with content-type and content-disposition", async () => {
    const zip = new Response("PKzipbytes", {
      status: 200,
      headers: {
        "content-type": "application/zip",
        "content-disposition": 'attachment; filename="My_Song_Export.zip"',
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(zip)
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx("j1")
    )
    expect(res.status).toBe(200)
    expect(res.headers.get("content-type")).toBe("application/zip")
    expect(res.headers.get("content-disposition")).toContain(
      "My_Song_Export.zip"
    )

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/studio/export/daw/j1")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("passes a 404 through as JSON for an unknown job", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 })
      )
    )
    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx("missing")
    )
    expect(res.status).toBe(404)
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await GET(
      req({ headers: { authorization: "Bearer tok" } }),
      ctx("j1")
    )
    expect(res.status).toBe(502)
  })
})
