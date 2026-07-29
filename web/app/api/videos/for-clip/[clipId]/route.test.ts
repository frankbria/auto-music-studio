import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { GET } from "@/app/api/videos/for-clip/[clipId]/route"

const ctx = (clipId: string) => ({ params: Promise.resolve({ clipId }) })

function req(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(new URL("http://localhost/api/videos/for-clip/c1"), { headers })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/videos/for-clip/[clipId]", () => {
  it("resolves anonymously (public song page) and passes the video through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "v1", published: true }), { status: 200 })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req(), ctx("c1"))
    expect(res.status).toBe(200)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/videos/for-clip/c1")
    // No auth header forwarded when the caller is anonymous.
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>).authorization).toBeUndefined()
  })

  it("forwards the owner's token when present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    await GET(req({ authorization: "Bearer tok" }), ctx("c1"))
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("passes a 404 through when the clip has no published video", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Video not found." }), { status: 404 })
      )
    )
    const res = await GET(req(), ctx("c1"))
    expect(res.status).toBe(404)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await GET(req(), ctx("c1"))
    expect(res.status).toBe(502)
  })
})
