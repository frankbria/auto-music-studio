import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { ACCESS_COOKIE } from "@/lib/auth"
import { GET } from "@/app/api/videos/[jobId]/stream/route"

function req(
  url: string,
  init: { headers?: Record<string, string>; cookie?: string } = {}
): NextRequest {
  const r = new NextRequest(new URL(url), { headers: init.headers })
  if (init.cookie) r.cookies.set(ACCESS_COOKIE, init.cookie)
  return r
}

const ctx = (jobId: string) => ({ params: Promise.resolve({ jobId }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/videos/[jobId]/stream", () => {
  it("proxies to the backend video stream and does not 401 without a header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("mp4", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req("http://localhost/api/videos/v1/stream"), ctx("v1"))
    expect(res.status).toBe(200)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/videos/v1/stream")
  })

  it("falls back to the access cookie as a Bearer token (private video plays via <video src>)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("mp4", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/videos/v1/stream", { cookie: "cookieTok" }), ctx("v1"))
    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer cookieTok")
  })

  it("prefers an explicit Authorization header over the cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("mp4", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/videos/v1/stream", {
        headers: { authorization: "Bearer headerTok" },
        cookie: "cookieTok",
      }),
      ctx("v1")
    )
    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer headerTok")
  })

  it("forwards the download flag to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("mp4", {
        status: 200,
        headers: { "content-disposition": 'attachment; filename="video-v1.mp4"' },
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/videos/v1/stream?download=1"),
      ctx("v1")
    )
    expect(fetchMock.mock.calls[0][0]).toContain("?download=1")
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="video-v1.mp4"')
  })

  it("does not force download for a falsy download value (public proxy)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("mp4", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/videos/v1/stream?download=0"), ctx("v1"))
    expect(fetchMock.mock.calls[0][0]).not.toContain("download")
  })

  it("forwards Range and passes a 206 through with its range headers intact", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("part", {
        status: 206,
        headers: {
          "content-type": "video/mp4",
          "content-range": "bytes 0-9/100",
          "accept-ranges": "bytes",
        },
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/videos/v1/stream", { headers: { range: "bytes=0-9" } }),
      ctx("v1")
    )
    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).range).toBe("bytes=0-9")
    expect(res.status).toBe(206)
    expect(res.headers.get("content-range")).toBe("bytes 0-9/100")
    expect(res.headers.get("content-type")).toBe("video/mp4")
  })

  it("passes a 404 through for an unpublished/unknown video", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Video not found." }), { status: 404 })
      )
    )
    const res = await GET(req("http://localhost/api/videos/v1/stream"), ctx("v1"))
    expect(res.status).toBe(404)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await GET(req("http://localhost/api/videos/v1/stream"), ctx("v1"))
    expect(res.status).toBe(502)
  })
})
