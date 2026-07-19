import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth"
import { POST } from "./route"

function request(cookie?: string): NextRequest {
  const req = new NextRequest(
    new URL("http://localhost:3000/api/auth/refresh"),
    { method: "POST" }
  )
  if (cookie) req.cookies.set(REFRESH_COOKIE, cookie)
  return req
}

afterEach(() => vi.unstubAllGlobals())

describe("refresh route", () => {
  it("401s without a refresh cookie and never calls the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(request())
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("does not clear the cookie when the backend 401s (refresh-race safety)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }))
    )
    const res = await POST(request("stale-token"))
    expect(res.status).toBe(401)
    const setCookie = res.headers.get("set-cookie") ?? ""
    expect(setCookie).not.toContain("Max-Age=0")
  })

  it("rotates the cookie on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "a",
          refresh_token: "newR",
          expires_in: 900,
        }),
      }))
    )
    const res = await POST(request("old-token"))
    expect(res.status).toBe(200)
    const setCookie = res.headers.get("set-cookie") ?? ""
    expect(setCookie).toContain(`${REFRESH_COOKIE}=newR`)
    // The access token is mirrored into a clip-scoped httpOnly cookie (#282).
    expect(setCookie).toContain(`${ACCESS_COOKIE}=a`)
    expect(setCookie).toContain("Path=/api/clips")
    expect(await res.json()).toEqual({ access_token: "a", expires_in: 900 })
  })
})
