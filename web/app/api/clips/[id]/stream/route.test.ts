import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { ACCESS_COOKIE } from "@/lib/auth"
import { GET } from "@/app/api/clips/[id]/stream/route"

function req(
  url: string,
  init: { headers?: Record<string, string>; cookie?: string } = {}
): NextRequest {
  const r = new NextRequest(new URL(url), { headers: init.headers })
  if (init.cookie) r.cookies.set(ACCESS_COOKIE, init.cookie)
  return r
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

  it("forwards the real client IP so the limiter keys per visitor (#283)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/stream", {
        headers: { "x-forwarded-for": "198.51.100.7, 10.0.0.2" },
      }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>)["x-forwarded-for"]).toBe(
      "198.51.100.7"
    )
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

  it("falls back to the access cookie as a Bearer token when no header is present (private clip)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/stream", { cookie: "cookieTok" }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer cookieTok"
    )
  })

  it("prefers an explicit Authorization header over the access cookie", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("audio", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/stream", {
        headers: { authorization: "Bearer headerTok" },
        cookie: "cookieTok",
      }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer headerTok"
    )
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

  it("passes a 416 through, keeping the Content-Range that tells the client the real length", async () => {
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
    // RFC 9110: a 416 carries the resource length so the client can retry with
    // a satisfiable range. Dropping it strands a seeking player.
    expect(res.headers.get("content-range")).toBe("bytes */500")
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
