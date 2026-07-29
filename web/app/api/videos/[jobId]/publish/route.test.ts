import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { POST } from "@/app/api/videos/[jobId]/publish/route"

const ctx = (jobId: string) => ({ params: Promise.resolve({ jobId }) })

function req(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(new URL("http://localhost/api/videos/v1/publish"), {
    method: "POST",
    headers,
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/videos/[jobId]/publish", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(req(), ctx("v1"))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the Bearer token and passes the backend response through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "v1", published: true }), { status: 200 })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(req({ authorization: "Bearer tok" }), ctx("v1"))
    expect(res.status).toBe(200)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/videos/v1/publish")
    expect(opts.method).toBe("POST")
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
    expect(await res.json()).toEqual({ id: "v1", published: true })
  })

  it("passes a 404 through for an unowned/unknown video", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Video not found." }), { status: 404 })
      )
    )
    const res = await POST(req({ authorization: "Bearer tok" }), ctx("v1"))
    expect(res.status).toBe(404)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await POST(req({ authorization: "Bearer tok" }), ctx("v1"))
    expect(res.status).toBe(502)
  })
})
