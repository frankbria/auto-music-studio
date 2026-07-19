import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth"
import { POST } from "./route"

function request(cookie?: string): NextRequest {
  const req = new NextRequest(new URL("http://localhost:3000/api/auth/logout"), {
    method: "POST",
  })
  if (cookie) req.cookies.set(REFRESH_COOKIE, cookie)
  return req
}

afterEach(() => vi.unstubAllGlobals())

describe("logout route", () => {
  it("clears both the refresh and the access cookie", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 204 })))
    const res = await POST(request("some-token"))
    expect(res.status).toBe(204)
    const setCookie = res.headers.get("set-cookie") ?? ""
    expect(setCookie).toContain(`${REFRESH_COOKIE}=;`)
    expect(setCookie).toContain(`${ACCESS_COOKIE}=;`)
    // Both expire immediately.
    expect(setCookie.match(/Max-Age=0/g)?.length).toBe(2)
  })
})
