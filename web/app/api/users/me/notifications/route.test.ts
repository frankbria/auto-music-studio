import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { GET } from "@/app/api/users/me/notifications/route"
import { POST } from "@/app/api/users/me/notifications/read/route"

function req(
  path: string,
  init: ConstructorParameters<typeof NextRequest>[1] = {}
): NextRequest {
  return new NextRequest(new URL(`http://localhost${path}`), init)
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/users/me/notifications", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await GET(req("/api/users/me/notifications"))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the token and paging query and passes the body through", async () => {
    const page = {
      notifications: [{ id: "n1" }],
      unread_count: 1,
      has_more: false,
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(page), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("/api/users/me/notifications?offset=20&limit=5", {
        headers: { authorization: "Bearer tok" },
      })
    )

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual(page)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(
      /\/api\/v1\/users\/me\/notifications\?offset=20&limit=5$/
    )
    expect(opts.headers.authorization).toBe("Bearer tok")
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await GET(
      req("/api/users/me/notifications", {
        headers: { authorization: "Bearer tok" },
      })
    )
    expect(res.status).toBe(502)
  })
})

describe("POST /api/users/me/notifications/read", () => {
  it("401s without an Authorization header", async () => {
    const res = await POST(
      req("/api/users/me/notifications/read", { method: "POST", body: "{}" })
    )
    expect(res.status).toBe(401)
  })

  it("forwards token + body and passes the backend status through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ updated: 1 }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req("/api/users/me/notifications/read", {
        method: "POST",
        headers: {
          authorization: "Bearer tok",
          "content-type": "application/json",
        },
        body: JSON.stringify({ ids: ["n1"] }),
      })
    )

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ updated: 1 })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/v1\/users\/me\/notifications\/read$/)
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({ ids: ["n1"] })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await POST(
      req("/api/users/me/notifications/read", {
        method: "POST",
        headers: { authorization: "Bearer tok" },
        body: "{}",
      })
    )
    expect(res.status).toBe(502)
  })
})
