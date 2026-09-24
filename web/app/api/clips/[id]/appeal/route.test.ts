import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { PATCH, POST } from "@/app/api/clips/[id]/appeal/route"

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

function req(
  method: "POST" | "PATCH",
  headers: Record<string, string> = {},
  body: unknown = { reason: "not spam" }
): NextRequest {
  return new NextRequest(new URL("http://localhost/api/clips/c1/appeal"), {
    method,
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/clips/[id]/appeal", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(req("POST"), ctx("c1"))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards token + body and passes the backend status through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "You have already appealed this decision.",
          }),
          { status: 409 }
        )
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req("POST", { authorization: "Bearer tok" }),
      ctx("c1")
    )

    expect(res.status).toBe(409)
    expect(await res.json()).toEqual({
      detail: "You have already appealed this decision.",
    })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/appeal")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({ reason: "not spam" })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await POST(
      req("POST", { authorization: "Bearer tok" }),
      ctx("c1")
    )
    expect(res.status).toBe(502)
  })
})

describe("PATCH /api/clips/[id]/appeal", () => {
  it("401s without an Authorization header", async () => {
    const res = await PATCH(req("PATCH"), ctx("c1"))
    expect(res.status).toBe(401)
  })

  it("forwards token + body and passes the backend status through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "a1", status: "pending" }), {
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await PATCH(
      req("PATCH", { authorization: "Bearer tok" }, { context: "more info" }),
      ctx("c1")
    )

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ id: "a1", status: "pending" })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/appeal")
    expect(opts.method).toBe("PATCH")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({ context: "more info" })
  })
})
