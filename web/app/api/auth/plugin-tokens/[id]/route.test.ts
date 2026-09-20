import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DELETE } from "./route"

function request(auth?: string): NextRequest {
  return new NextRequest(
    new URL("http://localhost:3000/api/auth/plugin-tokens/65f1"),
    { method: "DELETE", headers: auth ? { authorization: auth } : undefined }
  )
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) })

afterEach(() => vi.unstubAllGlobals())

describe("plugin-tokens revoke route", () => {
  it("401s without an authorization header and never calls the backend", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const res = await DELETE(request(), ctx("65f1"))
    expect(res.status).toBe(401)
    expect(await res.json()).toEqual({ detail: "Not authenticated." })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards the bearer header and the id, returning a bodyless 204", async () => {
    const json = vi.fn()
    const fetchMock = vi.fn(async () => ({ ok: true, status: 204, json }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await DELETE(request("Bearer tok123"), ctx("65f1"))
    expect(res.status).toBe(204)
    expect(await res.text()).toBe("")
    // A 204 has no body -- reading it as JSON would turn a success into a parse error.
    expect(json).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/plugin-tokens/65f1"),
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({ authorization: "Bearer tok123" }),
      })
    )
  })

  it("passes a 404 through for an unknown token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({ detail: "Plugin token not found." }),
      }))
    )
    const res = await DELETE(request("Bearer tok123"), ctx("missing"))
    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: "Plugin token not found." })
  })

  it("502s when the backend fetch throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down")
      })
    )
    const res = await DELETE(request("Bearer tok123"), ctx("65f1"))
    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({
      detail: "Plugin token service is unavailable.",
    })
  })
})
