import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchJobStatus } from "@/lib/job-status"

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
  )
}

afterEach(() => vi.restoreAllMocks())

describe("fetchJobStatus", () => {
  it("sends the Bearer token to the job proxy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "queued" }), { status: 200 })
      )
    vi.stubGlobal("fetch", fetchMock)

    await fetchJobStatus("j1", "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/jobs/j1")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
  })

  it("maps completed → clip ids", async () => {
    mockFetch({ status: "completed", clip_ids: ["c1", "c2"] })
    expect(await fetchJobStatus("j1", "tok")).toEqual({
      kind: "completed",
      clipIds: ["c1", "c2"],
    })
  })

  it("maps failed → error message", async () => {
    mockFetch({ status: "failed", error: "boom" })
    expect(await fetchJobStatus("j1", "tok")).toEqual({
      kind: "failed",
      error: "boom",
    })
  })

  it("falls back to a generic message when failed has no error", async () => {
    mockFetch({ status: "failed" })
    const result = await fetchJobStatus("j1", "tok")
    expect(result).toMatchObject({ kind: "failed" })
    if (result.kind === "failed") expect(result.error).toMatch(/failed/i)
  })

  it("maps queued/processing → pending (with progress)", async () => {
    mockFetch({ status: "processing", progress: "step 2 of 5" })
    expect(await fetchJobStatus("j1", "tok")).toEqual({
      kind: "pending",
      progress: "step 2 of 5",
    })
  })

  it("maps 401 → unauthorized", async () => {
    mockFetch({ detail: "no" }, 401)
    expect(await fetchJobStatus("j1", "tok")).toEqual({ kind: "unauthorized" })
  })

  it("fails fast on a 404 (unknown/not-owned job) instead of polling", async () => {
    mockFetch({ detail: "Job not found." }, 404)
    const result = await fetchJobStatus("j1", "tok")
    expect(result).toMatchObject({ kind: "failed" })
  })

  it("treats a 5xx as transient (keep polling)", async () => {
    mockFetch({ detail: "down" }, 502)
    expect(await fetchJobStatus("j1", "tok")).toEqual({ kind: "transient" })
  })

  it("treats a network failure as transient", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    expect(await fetchJobStatus("j1", "tok")).toEqual({ kind: "transient" })
  })
})
