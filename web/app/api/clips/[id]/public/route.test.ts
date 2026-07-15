import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/clips/[id]/public/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]/public", () => {
  it("does NOT 401 without an Authorization header", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "c1", is_owner: false }), {
          status: 200,
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req("http://localhost/api/clips/c1/public"), ctx("c1"))
    expect(res.status).toBe(200)
    await expect(res.json()).resolves.toEqual({ id: "c1", is_owner: false })
  })

  it("omits the Authorization header when the caller is anonymous", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ id: "c1" }), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/clips/c1/public"), ctx("c1"))

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/public")
    expect((opts.headers as Record<string, string>).authorization).toBeUndefined()
  })

  it("forwards the Bearer token when present so the owner is recognized", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "c1", is_owner: true }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/clips/c1/public", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("passes backend error status and body through verbatim", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Clip not found." }), { status: 404 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req("http://localhost/api/clips/c1/public"), ctx("c1"))
    expect(res.status).toBe(404)
    await expect(res.json()).resolves.toEqual({ detail: "Clip not found." })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(req("http://localhost/api/clips/c1/public"), ctx("c1"))
    expect(res.status).toBe(502)
  })

  it("encodes the clip id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/clips/x/public"), ctx("a/b"))

    expect(fetchMock.mock.calls[0][0]).toContain("/clips/a%2Fb/public")
  })
})
