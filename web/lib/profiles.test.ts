import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchPublicProfile } from "@/lib/profiles"

const respond = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("fetchPublicProfile", () => {
  it("reads the profile through the BFF, without the leading @", async () => {
    const profile = { handle: "nova", display_name: "Nova", clips: [] }
    const fetchMock = respond(200, profile)
    vi.stubGlobal("fetch", fetchMock)

    await expect(fetchPublicProfile("@nova")).resolves.toEqual(profile)
    expect(fetchMock.mock.calls[0][0]).toBe("/api/discover/profiles/nova")
    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.has("authorization")).toBe(false)
  })

  it("sends the viewer's token when there is one", async () => {
    const fetchMock = respond(200, { handle: "nova", clips: [] })
    vi.stubGlobal("fetch", fetchMock)

    await fetchPublicProfile("nova", "tok")
    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get("authorization")).toBe("Bearer tok")
  })

  it("encodes the handle into the path", async () => {
    const fetchMock = respond(200, { handle: "a/b", clips: [] })
    vi.stubGlobal("fetch", fetchMock)

    await fetchPublicProfile("@a/b")
    expect(fetchMock.mock.calls[0][0]).toBe("/api/discover/profiles/a%2Fb")
  })

  it("returns null for an unknown handle", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "Profile not found." }))
    await expect(fetchPublicProfile("ghost")).resolves.toBeNull()
  })

  it("throws on any other failure", async () => {
    vi.stubGlobal("fetch", respond(502))
    await expect(fetchPublicProfile("nova")).rejects.toThrow("502")
  })
})
