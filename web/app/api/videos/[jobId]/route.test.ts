import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { GET } from "@/app/api/videos/[jobId]/route"

const ctx = (jobId: string) => ({ params: Promise.resolve({ jobId }) })

function req(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(new URL("http://localhost/api/videos/v1"), { headers })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/videos/[jobId]", () => {
  it("passes video metadata through and forwards a token when present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "v1", published: false }), { status: 200 })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req({ authorization: "Bearer tok" }), ctx("v1"))
    expect(res.status).toBe(200)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/videos/v1")
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("resolves anonymously (no token) for a published video", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    await GET(req(), ctx("v1"))
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>).authorization).toBeUndefined()
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await GET(req(), ctx("v1"))
    expect(res.status).toBe(502)
  })
})
