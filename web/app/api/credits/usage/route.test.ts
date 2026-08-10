import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET } from "@/app/api/credits/usage/route"

// The hop between the component tests (which stub fetch in the browser) and the FastAPI
// tests (which call the backend directly). The `days` window only exists on the wire, so
// dropping it here would silently serve a 30-day dashboard to a 7-day request.

function req(query = ""): NextRequest {
  return new Request(
    `http://localhost/api/credits/usage${query}`
  ) as unknown as NextRequest
}

function authed(query = ""): NextRequest {
  return new Request(`http://localhost/api/credits/usage${query}`, {
    headers: { authorization: "Bearer t" },
  }) as unknown as NextRequest
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("usage proxy", () => {
  it("401s without an Authorization header", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req())

    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the window and the bearer token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ window_days: 7 }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(authed("?days=7"))

    expect(res.status).toBe(200)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/credits/usage?days=7")
    expect(init.headers.authorization).toBe("Bearer t")
    expect(await res.json()).toEqual({ window_days: 7 })
  })

  it("passes the backend status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "nope" }), { status: 422 })
      )
    )

    const res = await GET(authed("?days=0"))

    expect(res.status).toBe(422)
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))

    const res = await GET(authed())

    expect(res.status).toBe(502)
  })
})
