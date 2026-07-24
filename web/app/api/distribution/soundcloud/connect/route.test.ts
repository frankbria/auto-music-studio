import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DELETE, POST } from "./route"

function post(auth: boolean): NextRequest {
  const req = new NextRequest(
    new URL("http://localhost:3000/api/distribution/soundcloud/connect"),
    { method: "POST" }
  )
  if (auth) req.headers.set("authorization", "Bearer tok")
  return req
}

afterEach(() => vi.unstubAllGlobals())

describe("soundcloud connect route", () => {
  it("401s without an Authorization header, without calling the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(post(false))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("returns the authorize URL and re-emits the backend PKCE cookies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ authorization_url: "https://soundcloud.com/connect?x=1" }),
        headers: {
          getSetCookie: () => [
            "sc_link_nonce_abc=nonceval; Path=/api/v1/distribution; HttpOnly",
            "sc_link_verifier_abc=verval; Path=/api/v1/distribution; HttpOnly",
          ],
        },
      }))
    )
    const res = await POST(post(true))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({
      authorization_url: "https://soundcloud.com/connect?x=1",
    })
    const setCookie = res.headers.get("set-cookie") ?? ""
    expect(setCookie).toContain("sc_link_nonce_abc=nonceval")
    expect(setCookie).toContain("sc_link_verifier_abc=verval")
    // Re-scoped to `/` so the callback route on a different path can read them back.
    expect(setCookie).toContain("Path=/")
  })

  it("passes a backend 503 (not configured) straight through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({ detail: "SoundCloud is not configured." }),
        headers: { getSetCookie: () => [] },
      }))
    )
    const res = await POST(post(true))
    expect(res.status).toBe(503)
  })

  it("forwards a DELETE disconnect and preserves the 204", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ status: 204 })))
    const res = await DELETE(post(true))
    expect(res.status).toBe(204)
  })
})
