import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/discover/clips/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ok = (body: unknown = { clips: [], next_cursor: null, total: 0 }) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/discover/clips", () => {
  it("relays the documented params and drops anything else", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req(
        "http://localhost/api/discover/clips?q=lofi&style=rock&bpm_min=90&bpm_max=120&key=C+major&model=m1&sort=newest&limit=12&cursor=abc&owner_id=evil"
      )
    )

    const url = new URL(fetchMock.mock.calls[0][0] as string)
    expect(url.pathname).toBe("/api/v1/discover/clips")
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: "lofi",
      style: "rock",
      bpm_min: "90",
      bpm_max: "120",
      key: "C major",
      model: "m1",
      sort: "newest",
      limit: "12",
      cursor: "abc",
    })
  })

  it("omits empty params and sends no query string when none are set", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(req("http://localhost/api/discover/clips?q=&style="))

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/discover\/clips$/)
  })

  it("never forwards Authorization, but does forward the client IP", async () => {
    const fetchMock = ok()
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req("http://localhost/api/discover/clips", {
        headers: {
          authorization: "Bearer tok",
          "x-forwarded-for": "198.51.100.7",
        },
      })
    )

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.authorization).toBeUndefined()
    expect(headers["x-forwarded-for"]).toBe("198.51.100.7")
  })

  it("passes the backend status and body through", async () => {
    const invalidCursor = new Response(
      JSON.stringify({ detail: "Invalid cursor." }),
      { status: 422 }
    )
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(invalidCursor))

    const res = await GET(req("http://localhost/api/discover/clips?cursor=bad"))
    expect(res.status).toBe(422)
    await expect(res.json()).resolves.toEqual({ detail: "Invalid cursor." })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(req("http://localhost/api/discover/clips"))
    expect(res.status).toBe(502)
  })
})
