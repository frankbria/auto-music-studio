import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { GET } from "./route"

function request(auth?: string): NextRequest {
  return new NextRequest(
    new URL("http://localhost:3000/api/auth/plugin-tokens"),
    { headers: auth ? { authorization: auth } : undefined }
  )
}

afterEach(() => vi.unstubAllGlobals())

describe("plugin-tokens list route", () => {
  it("401s without an authorization header and never calls the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await GET(request())
    expect(res.status).toBe(401)
    expect(await res.json()).toEqual({ detail: "Not authenticated." })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the bearer header and returns the list", async () => {
    const tokens = [
      {
        id: "65f1",
        created_at: "2026-09-19T12:00:00Z",
        expires_at: "2026-09-26T12:00:00Z",
      },
    ]
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => tokens,
    }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await GET(request("Bearer tok123"))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual(tokens)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/plugin-tokens"),
      expect.objectContaining({
        headers: expect.objectContaining({ authorization: "Bearer tok123" }),
      })
    )
  })

  it("passes through a non-OK status and body from the backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid token." }),
      }))
    )
    const res = await GET(request("Bearer bad"))
    expect(res.status).toBe(401)
    expect(await res.json()).toEqual({ detail: "Invalid token." })
  })

  it("502s when the backend fetch throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down")
      })
    )
    const res = await GET(request("Bearer tok123"))
    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({
      detail: "Plugin token service is unavailable.",
    })
  })
})
