import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"

import { config, proxy } from "@/proxy"
import { REFRESH_COOKIE } from "@/lib/auth"

function request(path: string, withSession: boolean): NextRequest {
  const req = new NextRequest(new URL(`http://localhost:3000${path}`))
  if (withSession) req.cookies.set(REFRESH_COOKIE, "some-refresh-token")
  return req
}

describe("proxy route protection", () => {
  it("redirects an unauthenticated visitor to /login, preserving the path", () => {
    const res = proxy(request("/create", false))
    const location = res.headers.get("location")!
    const url = new URL(location)
    expect(url.pathname).toBe("/login")
    expect(url.searchParams.get("from")).toBe("/create")
  })

  it("lets an authenticated visitor through", () => {
    const res = proxy(request("/create", true))
    expect(res.headers.get("location")).toBeNull()
  })

  it("gates the admin pages on the session cookie too (US-27.3)", () => {
    expect(config.matcher).toContain("/admin/:path*")
  })
})
