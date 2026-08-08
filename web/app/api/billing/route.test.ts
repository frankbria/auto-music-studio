import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { GET, POST } from "@/app/api/billing/[...path]/route"

// The billing proxy. Raised in review on PR #422: it allowed `topup` but forwarded only
// the method and auth header, so the pack id never reached the backend and every real
// purchase failed validation instead of opening Stripe Checkout.
//
// Neither existing layer caught it — the component tests stub `fetch` in the browser and
// never reach the proxy, and the API tests call FastAPI directly. This file is the hop
// in between, which is exactly where the bug lived.

function req(path: string, init: RequestInit = {}): NextRequest {
  return new Request(
    `http://localhost/api/billing/${path}`,
    init
  ) as unknown as NextRequest
}

function params(path: string[]) {
  return { params: Promise.resolve({ path }) }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("billing proxy", () => {
  it("401s without an Authorization header", async () => {
    const res = await GET(req("subscription"), params(["subscription"]))
    expect(res.status).toBe(401)
  })

  it("404s a path outside the allowlist", async () => {
    // The allowlist is what keeps the segment from being interpolated into the backend
    // URL, so an unknown path must not reach fetch at all.
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(
      req("../../admin", { headers: { authorization: "Bearer t" } }),
      params(["..", "..", "admin"])
    )

    expect(res.status).toBe(404)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the top-up body to the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ url: "https://x" }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req("topup", {
        method: "POST",
        headers: {
          authorization: "Bearer t",
          "content-type": "application/json",
        },
        body: JSON.stringify({ pack_id: "250" }),
      }),
      params(["topup"])
    )

    expect(res.status).toBe(200)
    const [, init] = fetchMock.mock.calls[0]
    // Buying the 250-pack and being charged for something else is the failure here.
    expect(JSON.parse(String(init.body))).toEqual({ pack_id: "250" })
    expect((init.headers as Record<string, string>)["content-type"]).toBe(
      "application/json"
    )
  })

  it("sends no body for a bodyless POST", async () => {
    // `checkout` and `portal` take no payload; forwarding an empty string would set a
    // content-type on a request that has nothing in it.
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ url: "https://x" }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    await POST(
      req("checkout", {
        method: "POST",
        headers: { authorization: "Bearer t" },
      }),
      params(["checkout"])
    )

    const [, init] = fetchMock.mock.calls[0]
    expect(init.body).toBeUndefined()
  })

  it("passes the backend status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "Unknown credit pack 'x'." }), {
            status: 400,
          })
        )
    )

    const res = await POST(
      req("topup", {
        method: "POST",
        headers: { authorization: "Bearer t" },
        body: JSON.stringify({ pack_id: "x" }),
      }),
      params(["topup"])
    )

    expect(res.status).toBe(400)
  })
})
