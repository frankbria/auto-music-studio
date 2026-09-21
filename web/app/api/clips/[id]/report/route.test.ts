import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { POST } from "@/app/api/clips/[id]/report/route"

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

function req(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(new URL("http://localhost/api/clips/c1/report"), {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ category: "spam" }),
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("POST /api/clips/[id]/report", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(req(), ctx("c1"))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards token + body and passes the backend status through", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "You have already reported this clip." }),
          { status: 409 }
        )
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await POST(req({ authorization: "Bearer tok" }), ctx("c1"))

    expect(res.status).toBe(409)
    expect(await res.json()).toEqual({
      detail: "You have already reported this clip.",
    })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c1/report")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({ category: "spam" })
  })

  it("502s when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const res = await POST(req({ authorization: "Bearer tok" }), ctx("c1"))
    expect(res.status).toBe(502)
  })
})
