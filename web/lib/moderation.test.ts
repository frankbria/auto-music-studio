import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ModerationError,
  applyClipAction,
  applyUserAction,
  decideAppeal,
  fetchAppeals,
  fetchModerationLog,
  fetchModerationQueue,
  filterQueue,
  formatLogAction,
  parseApiTime,
  sortQueue,
  type AppealQueueItem,
  type QueueItem,
} from "@/lib/moderation"

function item(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    clip_id: "c1",
    clip_deleted: false,
    title: "Song",
    style_tags: [],
    creator_id: "u2",
    creator_name: "Creator",
    creator_banned: false,
    visibility: "public",
    content_warning: false,
    report_count: 1,
    categories: { spam: 1 },
    moderation_flags: [],
    sources: ["report"],
    severity: 1,
    latest_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

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

describe("fetchModerationQueue", () => {
  it("GETs the admin queue with the bearer token and returns its items", async () => {
    const fetchMock = stubFetch(200, { items: [item()] })
    const items = await fetchModerationQueue("tok")
    expect(items).toEqual([item()])
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/moderation/queue")
    expect(opts.headers.authorization).toBe("Bearer tok")
  })

  it("throws a ModerationError carrying the backend detail and status", async () => {
    stubFetch(403, { detail: "Admin access required." })
    await expect(fetchModerationQueue("tok")).rejects.toMatchObject({
      name: "ModerationError",
      status: 403,
      message: "Admin access required.",
    })
  })

  it("throws a ModerationError when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")))
    await expect(fetchModerationQueue("tok")).rejects.toBeInstanceOf(
      ModerationError
    )
  })
})

describe("fetchModerationLog", () => {
  it("GETs the log with a limit and returns its entries", async () => {
    const entry = {
      id: "l1",
      actor_id: "a1",
      action: "approve",
      target_type: "clip",
      target_id: "c1",
      reason: null,
      details: {},
      created_at: "2026-09-01T00:00:00Z",
    }
    const fetchMock = stubFetch(200, { entries: [entry] })
    expect(await fetchModerationLog("tok", 50)).toEqual([entry])
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/admin/moderation/log?limit=50"
    )
  })
})

describe("applyClipAction / applyUserAction", () => {
  it("POSTs the clip action body and normalises results to ids", async () => {
    const fetchMock = stubFetch(200, {
      results: [
        { clip_id: "c1", ok: true },
        { clip_id: "c2", ok: false, detail: "Clip not found." },
      ],
    })
    const results = await applyClipAction("tok", "remove", ["c1", "c2"], "spam")
    expect(results).toEqual([
      { id: "c1", ok: true, detail: null },
      { id: "c2", ok: false, detail: "Clip not found." },
    ])
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/moderation/clips")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({
      action: "remove",
      clip_ids: ["c1", "c2"],
      reason: "spam",
    })
  })

  it("omits a blank reason", async () => {
    const fetchMock = stubFetch(200, { results: [] })
    await applyClipAction("tok", "approve", ["c1"], "   ")
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      action: "approve",
      clip_ids: ["c1"],
    })
  })

  it("POSTs the user action body", async () => {
    const fetchMock = stubFetch(200, {
      results: [{ user_id: "u2", ok: true }],
    })
    const results = await applyUserAction("tok", "ban", ["u2"], "abuse")
    expect(results).toEqual([{ id: "u2", ok: true, detail: null }])
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/moderation/users")
    expect(JSON.parse(opts.body)).toEqual({
      action: "ban",
      user_ids: ["u2"],
      reason: "abuse",
    })
  })

  it("splits a large selection into sequential batches of 100 and merges the results", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body))
      const ids: string[] = body.clip_ids ?? body.user_ids
      const key = body.clip_ids ? "clip_id" : "user_id"
      return new Response(
        JSON.stringify({ results: ids.map((id) => ({ [key]: id, ok: true })) }),
        { status: 200 }
      )
    })
    vi.stubGlobal("fetch", fetchMock)
    const ids = Array.from({ length: 250 }, (_, i) => `c${i}`)

    const results = await applyClipAction("tok", "approve", ids, "dupes")

    const bodies = fetchMock.mock.calls.map(([, init]) =>
      JSON.parse(String(init?.body))
    )
    expect(bodies.map((b) => b.clip_ids.length)).toEqual([100, 100, 50])
    expect(bodies.flatMap((b) => b.clip_ids)).toEqual(ids)
    expect(bodies.every((b) => b.reason === "dupes")).toBe(true)
    expect(results.map((r) => r.id)).toEqual(ids)

    fetchMock.mockClear()
    const users = Array.from({ length: 101 }, (_, i) => `u${i}`)
    expect(await applyUserAction("tok", "warn", users)).toHaveLength(101)
    expect(
      fetchMock.mock.calls.map(
        ([, init]) => JSON.parse(String(init?.body)).user_ids.length
      )
    ).toEqual([100, 1])
  })

  it("throws on a rejected request", async () => {
    stubFetch(422, { detail: [{ msg: "too many" }] })
    await expect(applyUserAction("tok", "warn", ["u2"])).rejects.toMatchObject({
      status: 422,
    })
  })
})

describe("sortQueue", () => {
  const a = item({
    clip_id: "a",
    report_count: 5,
    severity: 1,
    latest_at: "2026-09-01T00:00:00Z",
  })
  const b = item({
    clip_id: "b",
    report_count: 2,
    severity: 3,
    latest_at: "2026-09-03T00:00:00Z",
  })
  const c = item({
    clip_id: "c",
    report_count: 1,
    severity: 3,
    latest_at: "2026-09-02T00:00:00Z",
  })

  it("keeps the server order for report count", () => {
    expect(sortQueue([a, b, c], "reports").map((i) => i.clip_id)).toEqual([
      "a",
      "b",
      "c",
    ])
  })

  it("orders by severity, then report count", () => {
    expect(sortQueue([a, c, b], "severity").map((i) => i.clip_id)).toEqual([
      "b",
      "c",
      "a",
    ])
  })

  it("orders newest first", () => {
    expect(sortQueue([a, b, c], "newest").map((i) => i.clip_id)).toEqual([
      "b",
      "c",
      "a",
    ])
  })

  it("does not mutate its input", () => {
    const input = [a, b, c]
    sortQueue(input, "newest")
    expect(input.map((i) => i.clip_id)).toEqual(["a", "b", "c"])
  })
})

describe("filterQueue", () => {
  const reported = item({
    clip_id: "r",
    sources: ["report"],
    categories: { copyright: 2 },
  })
  const automated = item({
    clip_id: "x",
    sources: ["automated"],
    categories: {},
    report_count: 0,
  })

  it("filters by source", () => {
    expect(
      filterQueue([reported, automated], "automated", "all").map(
        (i) => i.clip_id
      )
    ).toEqual(["x"])
    expect(
      filterQueue([reported, automated], "report", "all").map((i) => i.clip_id)
    ).toEqual(["r"])
    expect(filterQueue([reported, automated], "all", "all")).toHaveLength(2)
  })

  it("filters by report category", () => {
    expect(
      filterQueue([reported, automated], "all", "copyright").map(
        (i) => i.clip_id
      )
    ).toEqual(["r"])
    expect(filterQueue([reported, automated], "all", "spam")).toEqual([])
  })
})

describe("formatLogAction", () => {
  it("labels known actions and falls back for new ones", () => {
    expect(formatLogAction("ban")).toBe("Banned user")
    expect(formatLogAction("update_screening_rules")).toBe(
      "Updated screening rules"
    )
    expect(formatLogAction("something_new")).toBe("something new")
  })

  it("labels the appeal decision actions (US-27.4)", () => {
    expect(formatLogAction("appeal_upheld")).toBe("Upheld appeal")
    expect(formatLogAction("appeal_reversed")).toBe("Reversed appeal")
    expect(formatLogAction("appeal_info_requested")).toBe(
      "Requested appeal info"
    )
  })
})

describe("parseApiTime", () => {
  // The API sends naive UTC ("...T23:32:56.360000", no offset), which `new Date`
  // would read as local time. Run under a non-UTC TZ to see the difference.
  it("reads an offset-less timestamp as UTC", () => {
    expect(parseApiTime("2026-09-21T23:32:56.360000").toISOString()).toBe(
      "2026-09-21T23:32:56.360Z"
    )
  })

  it("keeps an explicit offset", () => {
    expect(parseApiTime("2026-09-21T19:32:56-04:00").toISOString()).toBe(
      "2026-09-21T23:32:56.000Z"
    )
    expect(parseApiTime("2026-09-21T23:32:56Z").toISOString()).toBe(
      "2026-09-21T23:32:56.000Z"
    )
  })
})

function appealItem(overrides: Partial<AppealQueueItem> = {}): AppealQueueItem {
  return {
    id: "ap1",
    clip_id: "c1",
    action: "remove",
    reason: "not spam",
    context: null,
    status: "pending",
    admin_note: null,
    created_at: "2026-09-01T00:00:00Z",
    decided_at: null,
    clip_title: "Song",
    clip_deleted: false,
    creator_id: "u2",
    creator_name: "Creator",
    action_reason: "spam",
    action_at: "2026-08-30T00:00:00Z",
    ...overrides,
  }
}

describe("fetchAppeals", () => {
  it("GETs the open queue by default", async () => {
    const fetchMock = stubFetch(200, { appeals: [appealItem()] })
    const items = await fetchAppeals("tok")
    expect(items).toEqual([appealItem()])
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/moderation/appeals?status=open")
    expect(opts.headers.authorization).toBe("Bearer tok")
  })

  it("passes through an explicit status filter", async () => {
    const fetchMock = stubFetch(200, { appeals: [] })
    await fetchAppeals("tok", "all")
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/admin/moderation/appeals?status=all"
    )
  })

  it("throws a ModerationError on failure", async () => {
    stubFetch(403, { detail: "Admin access required." })
    await expect(fetchAppeals("tok")).rejects.toMatchObject({
      name: "ModerationError",
      status: 403,
    })
  })
})

describe("decideAppeal", () => {
  it("POSTs the decision and an optional trimmed note", async () => {
    const fetchMock = stubFetch(200, appealItem({ status: "reversed" }))
    const result = await decideAppeal("tok", "ap1", "reverse", "  looks fine  ")
    expect(result).toEqual(appealItem({ status: "reversed" }))
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/moderation/appeals/ap1")
    expect(opts.method).toBe("POST")
    expect(JSON.parse(opts.body)).toEqual({
      decision: "reverse",
      note: "looks fine",
    })
  })

  it("omits note when blank", async () => {
    const fetchMock = stubFetch(200, appealItem({ status: "upheld" }))
    await decideAppeal("tok", "ap1", "uphold", "   ")
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      decision: "uphold",
    })
  })

  it("throws a ModerationError carrying the 409 detail", async () => {
    stubFetch(409, { detail: "This appeal has already been decided." })
    await expect(decideAppeal("tok", "ap1", "uphold")).rejects.toMatchObject({
      status: 409,
      message: "This appeal has already been decided.",
    })
  })
})
