import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { GET, POST } from "@/app/api/admin/[...path]/route"

const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) })

function req(
  url: string,
  init: {
    method?: string
    headers?: Record<string, string>
    body?: string
  } = {}
): NextRequest {
  return new NextRequest(new URL(url, "http://localhost"), init)
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("/api/admin/[...path]", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await GET(
      req("/api/admin/moderation/queue"),
      ctx(["moderation", "queue"])
    )
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards a GET with its query string and passes status + body through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ entries: [] }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("/api/admin/moderation/log?limit=50", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx(["moderation", "log"])
    )

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ entries: [] })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/v1\/admin\/moderation\/log\?limit=50$/)
    expect(opts.method).toBe("GET")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(opts.body).toBeUndefined()
  })

  it("forwards a POST body and the backend's rejection verbatim", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Admin access required." }), {
          status: 403,
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const body = JSON.stringify({ action: "ban", user_ids: ["u2"] })
    const res = await POST(
      req("/api/admin/moderation/users", {
        method: "POST",
        headers: {
          authorization: "Bearer tok",
          "content-type": "application/json",
        },
        body,
      }),
      ctx(["moderation", "users"])
    )

    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({ detail: "Admin access required." })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/v1\/admin\/moderation\/users$/)
    expect(opts.method).toBe("POST")
    expect(opts.headers["content-type"]).toBe("application/json")
    expect(JSON.parse(opts.body)).toEqual({ action: "ban", user_ids: ["u2"] })
  })

  it("refuses dot segments so a crafted path cannot climb out of /admin", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await GET(
      req("/api/admin/x", { headers: { authorization: "Bearer tok" } }),
      ctx(["..", "users"])
    )
    expect(res.status).toBe(404)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("encodes each path segment", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 404 }))
    vi.stubGlobal("fetch", fetchMock)
    await GET(
      req("/api/admin/x", { headers: { authorization: "Bearer tok" } }),
      ctx(["moderation", "a?b=1"])
    )
    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/api\/v1\/admin\/moderation\/a%3Fb%3D1$/
    )
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await GET(
      req("/api/admin/moderation/queue", {
        headers: { authorization: "Bearer tok" },
      }),
      ctx(["moderation", "queue"])
    )
    expect(res.status).toBe(502)
  })
})
