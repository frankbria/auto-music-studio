import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { POST } from "@/app/api/generate/route"

function req(init: RequestInit = {}): NextRequest {
  return new Request("http://localhost/api/generate", {
    method: "POST",
    ...init,
  }) as unknown as NextRequest
}

afterEach(() => vi.restoreAllMocks())

describe("POST /api/generate", () => {
  it("401s without an Authorization header", async () => {
    const res = await POST(req())
    expect(res.status).toBe(401)
  })

  it("forwards the Bearer token and body, passing 202 through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "j1", status: "queued" }), {
        status: 202,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(
      req({
        headers: {
          authorization: "Bearer tok",
          "content-type": "application/json",
        },
        body: JSON.stringify({ prompt: "hi", instrumental: false }),
      })
    )
    expect(res.status).toBe(202)
    expect(await res.json()).toMatchObject({ job_id: "j1" })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/generate")
    expect(opts.method).toBe("POST")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(opts.body).toBe(JSON.stringify({ prompt: "hi", instrumental: false }))
  })

  it("surfaces a 422 verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "bad" }), { status: 422 })
      )
    )
    const res = await POST(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" })
    )
    expect(res.status).toBe(422)
    expect(await res.json()).toEqual({ detail: "bad" })
  })
})
