import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { POST } from "./route"

function request(auth?: string): NextRequest {
  return new NextRequest(
    new URL("http://localhost:3000/api/auth/plugin-token"),
    {
      method: "POST",
      headers: auth ? { authorization: auth } : undefined,
    }
  )
}

afterEach(() => vi.unstubAllGlobals())

describe("plugin-token route", () => {
  it("401s without an authorization header and never calls the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await POST(request())
    expect(res.status).toBe(401)
    expect(await res.json()).toEqual({ detail: "Not authenticated." })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the bearer header to the backend", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: "a",
        refresh_token: "plugin-r",
        token_type: "bearer",
        expires_in: 604800,
      }),
    }))
    vi.stubGlobal("fetch", fetchMock)
    await POST(request("Bearer tok123"))

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/plugin-token"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ authorization: "Bearer tok123" }),
      })
    )
  })

  it("strips the access_token from the response, returning only the refresh_token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "should-not-leak",
          refresh_token: "plugin-r",
          token_type: "bearer",
          expires_in: 604800,
        }),
      }))
    )
    const res = await POST(request("Bearer tok123"))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body).toEqual({ refresh_token: "plugin-r" })
    expect(JSON.stringify(body)).not.toContain("should-not-leak")
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
    const res = await POST(request("Bearer bad"))
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
    const res = await POST(request("Bearer tok123"))
    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({
      detail: "Plugin token service is unavailable.",
    })
  })
})
