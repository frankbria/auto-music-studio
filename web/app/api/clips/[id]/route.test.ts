import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { DELETE, GET } from "@/app/api/clips/[id]/route"

function req(url: string, init: RequestInit = {}): NextRequest {
  return new Request(url, init) as unknown as NextRequest
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("GET /api/clips/[id]", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req("http://localhost/api/clips/c1"), ctx("c1"))
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and clip id to the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "c1" }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("http://localhost/api/clips/c1", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(200)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("passes a 404 through for an unknown clip", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 })
      )
    )
    const res = await GET(
      req("http://localhost/api/clips/missing", {
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
      req("http://localhost/api/clips/c1", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})

describe("DELETE /api/clips/[id]", () => {
  it("401s without an Authorization header", async () => {
    const res = await DELETE(
      req("http://localhost/api/clips/c1", { method: "DELETE" }),
      ctx("c1")
    )
    expect(res.status).toBe(401)
  })

  it("forwards the delete to the backend and passes 204 through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await DELETE(
      req("http://localhost/api/clips/c1", {
        method: "DELETE",
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(204)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1")
    expect(opts.method).toBe("DELETE")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("passes a 404 through for an unknown clip", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 })
      )
    )
    const res = await DELETE(
      req("http://localhost/api/clips/missing", {
        method: "DELETE",
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
    const res = await DELETE(
      req("http://localhost/api/clips/c1", {
        method: "DELETE",
        headers: { authorization: "Bearer tok" },
      }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})
