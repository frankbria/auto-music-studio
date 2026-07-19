import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth"
import { POST } from "./route"

function request(body: unknown): NextRequest {
  return new NextRequest(
    new URL("http://localhost:3000/api/auth/callback/google"),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }
  )
}

const ctx = { params: Promise.resolve({ provider: "google" }) }

afterEach(() => vi.unstubAllGlobals())

describe("callback route", () => {
  it("sets both the refresh and clip-scoped access cookie on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "a",
          refresh_token: "r",
          expires_in: 900,
        }),
      }))
    )

    const res = await POST(request({ code: "c", state: "s" }), ctx)
    expect(res.status).toBe(200)
    const setCookie = res.headers.get("set-cookie") ?? ""
    expect(setCookie).toContain(`${REFRESH_COOKIE}=r`)
    expect(setCookie).toContain(`${ACCESS_COOKIE}=a`)
    expect(setCookie).toContain("Path=/api/clips")
    expect(await res.json()).toEqual({ access_token: "a", expires_in: 900 })
  })

  it("400s for an unknown provider without calling the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(request({ code: "c", state: "s" }), {
      params: Promise.resolve({ provider: "nope" }),
    })
    expect(res.status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
