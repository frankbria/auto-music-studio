import { afterEach, describe, expect, it, vi } from "vitest"

import {
  addAppealContext,
  fetchMyAppeals,
  appealFor,
  appealsByClip,
  submitClipAppeal,
  type AppealView,
} from "@/lib/appeals"

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }))
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const appeal: AppealView = {
  id: "a1",
  clip_id: "c1",
  action: "remove",
  reason: "not spam",
  context: null,
  status: "pending",
  admin_note: null,
  created_at: "2026-01-01T00:00:00Z",
  decided_at: null,
}

describe("submitClipAppeal", () => {
  it("posts the trimmed reason/context and returns the confirmation", async () => {
    const fetchMock = stubFetch(201, appeal)
    const result = await submitClipAppeal(
      "c1",
      "  not spam  ",
      "  extra info  ",
      "tok"
    )
    expect(result).toEqual({
      status: "submitted",
      appeal,
      message: "Appeal submitted. Our team will review it.",
    })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/appeal")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({
      reason: "not spam",
      context: "extra info",
    })
  })

  it("omits an empty context", async () => {
    const fetchMock = stubFetch(201, appeal)
    await submitClipAppeal("c1", "reason", "  ", "tok")
    const [, opts] = fetchMock.mock.calls[0]
    expect(JSON.parse(opts.body)).toEqual({ reason: "reason", context: null })
  })

  it("shows the duplicate message on a 409", async () => {
    stubFetch(409, { detail: "You have already appealed this decision." })
    const result = await submitClipAppeal("c1", "reason", "", "tok")
    expect(result).toEqual({
      status: "error",
      detail: "You have already appealed this decision.",
    })
  })

  it("falls back to a generic message when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    const result = await submitClipAppeal("c1", "reason", "", "tok")
    expect(result).toEqual({
      status: "error",
      detail: "Could not submit the appeal. Please try again.",
    })
  })
})

describe("addAppealContext", () => {
  it("PATCHes the trimmed context", async () => {
    const infoRequested = { ...appeal, status: "pending" as const }
    const fetchMock = stubFetch(200, infoRequested)
    const result = await addAppealContext("c1", "  more info  ", "tok")
    expect(result).toEqual({
      status: "submitted",
      appeal: infoRequested,
      message: "Additional information sent.",
    })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/appeal")
    expect(opts.method).toBe("PATCH")
    expect(JSON.parse(opts.body)).toEqual({ context: "more info" })
  })

  it("surfaces a 409 detail", async () => {
    stubFetch(409, { detail: "No information was requested." })
    const result = await addAppealContext("c1", "more", "tok")
    expect(result).toEqual({
      status: "error",
      detail: "No information was requested.",
    })
  })
})

describe("fetchMyAppeals", () => {
  it("returns the caller's appeals", async () => {
    stubFetch(200, { appeals: [appeal] })
    const result = await fetchMyAppeals("tok")
    expect(result).toEqual([appeal])
  })

  it("never throws — returns [] on a failed request", async () => {
    stubFetch(500, {})
    expect(await fetchMyAppeals("tok")).toEqual([])
  })

  it("never throws — returns [] on a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))
    expect(await fetchMyAppeals("tok")).toEqual([])
  })
})

describe("appealsByClip / appealFor", () => {
  const flagOpen: AppealView = {
    ...appeal,
    id: "a1",
    action: "flag",
    status: "pending",
  }
  const removeUpheld: AppealView = {
    ...appeal,
    id: "a2",
    action: "remove",
    status: "upheld",
  }
  const removeReversed: AppealView = { ...removeUpheld, status: "reversed" }
  const byClip = (list: AppealView[]) => appealsByClip(list).get("c1") ?? []

  it("groups newest-first appeals per clip", () => {
    const map = appealsByClip([removeUpheld, flagOpen])
    expect(map.get("c1")).toEqual([removeUpheld, flagOpen])
    expect(map.size).toBe(1)
  })

  it("picks the removal appeal while the clip is removed, even over an open flag appeal", () => {
    const clip = { removed_at: "2026-02-01T00:00:00Z", content_warning: true }
    expect(appealFor(clip, byClip([removeUpheld, flagOpen]))).toEqual(
      removeUpheld
    )
  })

  it("picks the flag appeal once the removal is reversed and the flag remains", () => {
    const clip = { removed_at: null, content_warning: true }
    expect(appealFor(clip, byClip([removeReversed, flagOpen]))).toEqual(
      flagOpen
    )
  })

  it("falls back to the newest appeal once the clip is clear", () => {
    const clip = { removed_at: null, content_warning: false }
    expect(appealFor(clip, byClip([removeReversed, flagOpen]))).toEqual(
      removeReversed
    )
  })

  it("is null without appeals", () => {
    expect(
      appealFor({ removed_at: null, content_warning: false }, [])
    ).toBeNull()
  })
})
