import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { POST as play } from "@/app/api/clips/[id]/play/route"
import { DELETE as unlike, PUT as like } from "@/app/api/clips/[id]/like/route"

// The engagement proxies (#656): play and share are open to a signed-out listener, like needs a token.

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

function req(
  path: string,
  method: string,
  headers: Record<string, string> = {}
) {
  return new NextRequest(new URL(`http://localhost${path}`), {
    method,
    headers,
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/clips/[id]/play", () => {
  it("forwards a signed-out play without a token and passes the 204 through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await play(req("/api/clips/c1/play", "POST"), ctx("c1"))

    expect(res.status).toBe(204)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/play")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBeUndefined()
  })

  it("forwards the token when there is one, and the backend's 404", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Clip not found." }), {
        status: 404,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await play(
      req("/api/clips/c1/play", "POST", { authorization: "Bearer tok" }),
      ctx("c1")
    )

    expect(res.status).toBe(404)
    expect(fetchMock.mock.calls[0][1].headers.authorization).toBe("Bearer tok")
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    expect(
      (await play(req("/api/clips/c1/play", "POST"), ctx("c1"))).status
    ).toBe(502)
  })
})

describe("PUT/DELETE /api/clips/[id]/like", () => {
  it("401s without a token and never reaches the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    expect(
      (await like(req("/api/clips/c1/like", "PUT"), ctx("c1"))).status
    ).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    ["PUT", like],
    ["DELETE", unlike],
  ] as const)(
    "forwards %s with the token and returns the like state",
    async (method, handler) => {
      const fetchMock = vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ liked: method === "PUT", like_count: 3 }),
            { status: 200 }
          )
        )
      vi.stubGlobal("fetch", fetchMock)

      const res = await handler(
        req("/api/clips/c1/like", method, { authorization: "Bearer tok" }),
        ctx("c1")
      )

      expect(await res.json()).toEqual({
        liked: method === "PUT",
        like_count: 3,
      })
      expect(fetchMock.mock.calls[0][1].method).toBe(method)
    }
  )
})
