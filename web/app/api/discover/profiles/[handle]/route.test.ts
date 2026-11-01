import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/discover/profiles/[handle]/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (handle: string) => ({ params: Promise.resolve({ handle }) })

const ok = (body: unknown = { handle: "nova", clips: [] }) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/discover/profiles/[handle]", () => {
  it("proxies to the backend profile, encoding the handle", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/discover/profiles/a%2Fb"), ctx("a/b"))

    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/api\/v1\/discover\/profiles\/a%2Fb$/
    )
  })

  it("forwards the viewer's Authorization and the client IP", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/discover/profiles/nova", {
        headers: {
          authorization: "Bearer tok",
          "x-forwarded-for": "198.51.100.7",
        },
      }),
      ctx("nova")
    )

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.authorization).toBe("Bearer tok")
    expect(headers["x-forwarded-for"]).toBe("198.51.100.7")
  })

  it("sends no Authorization for an anonymous visitor", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/discover/profiles/nova"), ctx("nova"))

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.authorization).toBeUndefined()
  })

  it("passes the backend status and body through", async () => {
    const missing = new Response(
      JSON.stringify({ detail: "Profile not found." }),
      { status: 404 }
    )
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(missing))

    const res = await GET(
      req("http://localhost/api/discover/profiles/ghost"),
      ctx("ghost")
    )
    expect(res.status).toBe(404)
    await expect(res.json()).resolves.toEqual({ detail: "Profile not found." })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(
      req("http://localhost/api/discover/profiles/nova"),
      ctx("nova")
    )
    expect(res.status).toBe(502)
  })
})
