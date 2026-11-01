import { afterEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

import { PATCH, POST } from "@/app/api/videos/[jobId]/appeal/route"

const ctx = (jobId: string) => ({ params: Promise.resolve({ jobId }) })

function req(
  method: "POST" | "PATCH",
  headers: Record<string, string> = {},
  body: unknown = { reason: "my own footage" }
): NextRequest {
  return new NextRequest(new URL("http://localhost/api/videos/v1/appeal"), {
    method,
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("/api/videos/[jobId]/appeal (#623)", () => {
  it("401s without an Authorization header (never reaches the backend)", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(req("POST"), ctx("v1"))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    ["POST", POST, 201],
    ["PATCH", PATCH, 200],
  ] as const)(
    "forwards %s to the video's appeal and passes the status through",
    async (method, handler, status) => {
      const fetchMock = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ id: "a1" }), { status })
        )
      vi.stubGlobal("fetch", fetchMock)

      const res = await handler(
        req(method, { authorization: "Bearer tok" }),
        ctx("v1")
      )

      expect(res.status).toBe(status)
      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toMatch(/\/api\/v1\/videos\/v1\/appeal$/)
      expect(init.method).toBe(method)
      expect(init.headers.authorization).toBe("Bearer tok")
    }
  )
})
