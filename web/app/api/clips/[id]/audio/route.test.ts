import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/[id]/audio/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]/audio", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req("http://localhost/api/clips/c1/audio"), ctx("c1"))
    expect(res.status).toBe(401)
  })

  it("forwards the token and format query, passing audio bytes through", async () => {
    const bytes = new Uint8Array([1, 2, 3])
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(bytes, {
        status: 200,
        headers: { "content-type": "audio/mpeg" },
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips/c1/audio?format=mp3", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(200)
    expect(res.headers.get("content-type")).toBe("audio/mpeg")
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(bytes)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/audio")
    expect(url).toContain("format=mp3")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("omits the format query when none is requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1]), {
        status: 200,
        headers: { "content-type": "audio/wav" },
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/audio", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    const [url] = fetchMock.mock.calls[0]
    expect(url).not.toContain("format=")
  })

  it("passes backend errors through as JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "not found" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        })
      )
    )
    const res = await GET(
      req("http://localhost/api/clips/missing/audio", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("missing")
    )
    expect(res.status).toBe(404)
  })

  it("returns 502 when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("ECONNREFUSED"))
    )
    const res = await GET(
      req("http://localhost/api/clips/c1/audio", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})
