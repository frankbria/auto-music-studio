import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"

import { middleware } from "@/middleware"
import { REFRESH_COOKIE } from "@/lib/auth"

function request(path: string, withSession: boolean): NextRequest {
  const req = new NextRequest(new URL(`http://localhost:3000${path}`))
  if (withSession) req.cookies.set(REFRESH_COOKIE, "some-refresh-token")
  return req
}

describe("middleware route protection", () => {
  it("redirects an unauthenticated visitor to /login, preserving the path", () => {
    const res = middleware(request("/create", false))
    const location = res.headers.get("location")!
    const url = new URL(location)
    expect(url.pathname).toBe("/login")
    expect(url.searchParams.get("from")).toBe("/create")
  })

  it("lets an authenticated visitor through", () => {
    const res = middleware(request("/create", true))
    expect(res.headers.get("location")).toBeNull()
  })
})
