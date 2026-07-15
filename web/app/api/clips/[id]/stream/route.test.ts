import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/[id]/stream/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]/stream", () => {
  it("does NOT 401 without an Authorization header", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req("http://localhost/api/clips/c1/stream"), ctx("c1"))
    expect(res.status).toBe(200)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/clips/c1/stream")
  })

  it("forwards the Bearer token when present", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/stream", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("forwards the Range header and passes a 206 through with its range headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("part", {
        status: 206,
        headers: {
          "content-type": "audio/wav",
          "content-range": "bytes 0-99/500",
          "accept-ranges": "bytes",
          "cache-control": "public, max-age=3600",
        },
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips/c1/stream", {
        headers: { range: "bytes=0-99" },
      }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).range).toBe("bytes=0-99")

    expect(res.status).toBe(206)
    expect(res.headers.get("content-range")).toBe("bytes 0-99/500")
    expect(res.headers.get("accept-ranges")).toBe("bytes")
    expect(res.headers.get("cache-control")).toBe("public, max-age=3600")
    expect(res.headers.get("content-type")).toBe("audio/wav")
  })

  it("omits the Range header when the client sent none", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/clips/c1/stream"), ctx("c1"))

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).range).toBeUndefined()
  })

  it("forwards the format query", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/clips/c1/stream?format=mp3"), ctx("c1"))

    expect(fetchMock.mock.calls[0][0]).toContain("?format=mp3")
  })

  it("passes a 416 through (unsatisfiable range)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "bad range" }), {
          status: 416,
          headers: { "content-range": "bytes */500" },
        })
      )
    )

    const res = await GET(
      req("http://localhost/api/clips/c1/stream", {
        headers: { range: "bytes=9999-" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(416)
  })

  it("passes a 404 through for a private or unknown clip", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Clip not found." }), { status: 404 })
      )
    )

    const res = await GET(req("http://localhost/api/clips/c1/stream"), ctx("c1"))
    expect(res.status).toBe(404)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(req("http://localhost/api/clips/c1/stream"), ctx("c1"))
    expect(res.status).toBe(502)
  })
})
