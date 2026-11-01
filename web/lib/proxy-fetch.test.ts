import { describe, expect, it } from "vitest"

import {
  JSON_BODY_LIMIT,
  clientIpHeaders,
  readBodyCapped,
  readTextCapped,
} from "@/lib/proxy-fetch"

const withHeaders = (h: Record<string, string>) => ({ headers: new Headers(h) })

describe("clientIpHeaders (#283)", () => {
  it("uses the leftmost X-Forwarded-For entry (original client)", () => {
    expect(
      clientIpHeaders(
        withHeaders({ "x-forwarded-for": "198.51.100.7, 10.0.0.2" })
      )
    ).toEqual({ "x-forwarded-for": "198.51.100.7" })
  })

  it("falls back to X-Real-IP when no X-Forwarded-For is present", () => {
    expect(
      clientIpHeaders(withHeaders({ "x-real-ip": "203.0.113.9" }))
    ).toEqual({
      "x-forwarded-for": "203.0.113.9",
    })
  })

  it("forwards nothing when the client IP is unknown (local dev)", () => {
    expect(clientIpHeaders(withHeaders({}))).toEqual({})
  })
})

/** A streamed body with no Content-Length, so only the byte count can catch it. */
function streamed(bytes: number): Request {
  const chunk = new Uint8Array(64 * 1024)
  let sent = 0
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent >= bytes) return controller.close()
      sent += chunk.byteLength
      controller.enqueue(chunk)
    },
  })
  return new Request("http://localhost/x", {
    method: "POST",
    body,
    duplex: "half",
  } as RequestInit)
}

describe("readBodyCapped (#567)", () => {
  it("returns a body up to the limit", async () => {
    const req = new Request("http://localhost/x", {
      method: "POST",
      body: '{"a":1}',
    })
    expect(await readTextCapped(req)).toBe('{"a":1}')
  })

  it("refuses a declared Content-Length over the limit without reading", async () => {
    const req = new Request("http://localhost/x", {
      method: "POST",
      body: "x",
      headers: { "content-length": String(JSON_BODY_LIMIT + 1) },
    })
    expect(await readBodyCapped(req)).toBeNull()
  })

  it("refuses a streamed body once it passes the limit", async () => {
    expect(
      await readBodyCapped(streamed(JSON_BODY_LIMIT + 64 * 1024))
    ).toBeNull()
  })

  it("reads an empty body as empty", async () => {
    const req = new Request("http://localhost/x", { method: "POST" })
    expect(await readTextCapped(req)).toBe("")
  })
})
