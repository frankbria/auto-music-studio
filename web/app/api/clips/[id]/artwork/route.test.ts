import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { ACCESS_COOKIE } from "@/lib/auth"
import { GET } from "@/app/api/clips/[id]/artwork/route"

function req(
  init: { headers?: Record<string, string>; cookie?: string } = {}
): NextRequest {
  const r = new NextRequest(new URL("http://localhost/api/clips/c1/artwork"), {
    headers: init.headers,
  })
  if (init.cookie) r.cookies.set(ACCESS_COOKIE, init.cookie)
  return r
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

const png = () =>
  new Response("img", {
    status: 200,
    headers: { "content-type": "image/png", "content-length": "3" },
  })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]/artwork (#737)", () => {
  it("serves the image bytes anonymously for a public clip", async () => {
    const fetchMock = vi.fn().mockResolvedValue(png())
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req(), ctx("c1"))

    expect(res.status).toBe(200)
    expect(res.headers.get("content-type")).toBe("image/png")
    expect(await res.text()).toBe("img")
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/clips/c1/artwork")
    const [, opts] = fetchMock.mock.calls[0]
    expect(
      (opts.headers as Record<string, string>).authorization
    ).toBeUndefined()
  })

  it("falls back to the access cookie as a Bearer token so an <img> can load a private clip's art", async () => {
    const fetchMock = vi.fn().mockResolvedValue(png())
    vi.stubGlobal("fetch", fetchMock)

    await GET(req({ cookie: "cookieTok" }), ctx("c1"))

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer cookieTok"
    )
  })

  it("prefers an explicit Authorization header over the access cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(png())
    vi.stubGlobal("fetch", fetchMock)

    await GET(
      req({
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

  it("encodes the clip id into the backend path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(png())
    vi.stubGlobal("fetch", fetchMock)

    await GET(req(), ctx("a/b"))

    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/clips/a%2Fb/artwork")
  })

  it("passes a 404 through when the clip has no cover art", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "This clip has no cover art." }),
          {
            status: 404,
            headers: { "content-type": "application/json" },
          }
        )
      )
    )

    const res = await GET(req(), ctx("c1"))
    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: "This clip has no cover art." })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const res = await GET(req(), ctx("c1"))
    expect(res.status).toBe(502)
  })
})
