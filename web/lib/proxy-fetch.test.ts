import { describe, expect, it } from "vitest"

import { clientIpHeaders } from "@/lib/proxy-fetch"

const withHeaders = (h: Record<string, string>) => ({ headers: new Headers(h) })

describe("clientIpHeaders (#283)", () => {
  it("uses the leftmost X-Forwarded-For entry (original client)", () => {
    expect(
      clientIpHeaders(withHeaders({ "x-forwarded-for": "198.51.100.7, 10.0.0.2" }))
    ).toEqual({ "x-forwarded-for": "198.51.100.7" })
  })

  it("falls back to X-Real-IP when no X-Forwarded-For is present", () => {
    expect(clientIpHeaders(withHeaders({ "x-real-ip": "203.0.113.9" }))).toEqual({
      "x-forwarded-for": "203.0.113.9",
    })
  })

  it("forwards nothing when the client IP is unknown (local dev)", () => {
    expect(clientIpHeaders(withHeaders({}))).toEqual({})
  })
})
