import { afterEach, describe, expect, it, vi } from "vitest"

import { reportEngagement, saveLike, setStaffPick } from "@/lib/engagement"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("engagement client (#656)", () => {
  it("reports a play with the token when signed in, and without one when not", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    await reportEngagement("c1", "play", "tok")
    await reportEngagement("c1", "share", null)

    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/clips/c1/play",
      { method: "POST", headers: { authorization: "Bearer tok" } },
    ])
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/clips/c1/share",
      { method: "POST", headers: {} },
    ])
  })

  it("never lets a failed count reach the caller", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    await expect(reportEngagement("c1", "play")).resolves.toBeUndefined()
  })

  it("saves a like with PUT and an unlike with DELETE, and throws when it didn't save", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ liked: true, like_count: 1 }))
      )
      .mockResolvedValueOnce(new Response("{}", { status: 404 }))
    vi.stubGlobal("fetch", fetchMock)

    await expect(saveLike("c1", true, "tok")).resolves.toEqual({
      liked: true,
      like_count: 1,
    })
    await expect(saveLike("c1", false, "tok")).rejects.toThrow("404")
    expect(fetchMock.mock.calls.map(([, init]) => init.method)).toEqual([
      "PUT",
      "DELETE",
    ])
  })

  it("picks with PUT and unpicks with DELETE through the admin proxy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ staff_picked_at: "2026-11-02T00:00:00Z" })
        )
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ staff_picked_at: null }))
      )
    vi.stubGlobal("fetch", fetchMock)

    await expect(setStaffPick("c1", true, "tok")).resolves.toBe(
      "2026-11-02T00:00:00Z"
    )
    await expect(setStaffPick("c1", false, "tok")).resolves.toBeNull()
    expect(
      fetchMock.mock.calls.map(([url, init]) => [url, init.method])
    ).toEqual([
      ["/api/admin/clips/c1/staff-pick", "PUT"],
      ["/api/admin/clips/c1/staff-pick", "DELETE"],
    ])
  })
})
