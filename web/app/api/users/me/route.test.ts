import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET, PATCH } from "@/app/api/users/me/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request(
    "http://localhost/api/users/me",
    init
  ) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("GET /api/users/me", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req())
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and passes the profile through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "u1", handle: "ada" }), {
          status: 200,
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(req({ headers: { authorization: "Bearer tok" } }))
    expect(res.status).toBe(200)
    expect(await res.json()).toMatchObject({ id: "u1", handle: "ada" })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/users/me")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })
})

describe("PATCH /api/users/me", () => {
  it("forwards the body and surfaces a 409 verbatim", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "taken" }), { status: 409 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await PATCH(
      req({
        method: "PATCH",
        headers: {
          authorization: "Bearer tok",
          "content-type": "application/json",
        },
        body: JSON.stringify({ handle: "taken" }),
      })
    )
    expect(res.status).toBe(409)
    expect(await res.json()).toEqual({ detail: "taken" })

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.method).toBe("PATCH")
    expect(opts.body).toBe(JSON.stringify({ handle: "taken" }))
  })

  it("401s without an Authorization header", async () => {
    const res = await PATCH(req({ method: "PATCH" }))
    expect(res.status).toBe(401)
  })

  it("passes a 204 through without an empty {} body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    )
    const res = await PATCH(
      req({
        method: "PATCH",
        headers: { authorization: "Bearer tok" },
        body: "{}",
      })
    )
    expect(res.status).toBe(204)
    expect(await res.text()).toBe("")
  })
})
