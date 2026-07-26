import { afterEach, describe, expect, it, vi } from "vitest"

import {
  MAX_REFERENCE_IMAGES,
  VIDEO_ASPECT_RATIOS,
  VIDEO_FRAME_RATES,
  VIDEO_RESOLUTIONS,
  VIDEO_STYLE_PRESETS,
  VIDEO_TRANSITIONS,
  estimateVideoCost,
  fetchVideoStatus,
  presetLabel,
  submitVideoJob,
  type VideoConfig,
} from "@/lib/video"

const config: VideoConfig = {
  prompt: "neon city",
  style_preset: undefined,
  lyrics_sync: false,
  aspect_ratio: "16:9",
  resolution: "720p",
  frame_rate: 30,
  transitions: "auto",
}

function mockFetch(status: number, body: unknown) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("option tables", () => {
  it("mirror the backend literals", () => {
    expect(VIDEO_STYLE_PRESETS.map((p) => p.value)).toEqual([
      "abstract",
      "cinematic",
      "animated",
      "lyric_video",
      "live_performance",
      "nature",
    ])
    expect(VIDEO_ASPECT_RATIOS.map((a) => a.value)).toEqual(["16:9", "9:16", "1:1"])
    expect(VIDEO_RESOLUTIONS.map((r) => r.value)).toEqual(["720p", "1080p", "4k"])
    expect(VIDEO_FRAME_RATES.map((f) => f.value)).toEqual([24, 30, 60])
    expect(VIDEO_TRANSITIONS.map((t) => t.value)).toEqual([
      "auto",
      "cut",
      "fade",
      "dissolve",
    ])
    expect(MAX_REFERENCE_IMAGES).toBe(5)
  })

  it("marks exactly 1080p and 4k as Pro-only", () => {
    const proOnly = VIDEO_RESOLUTIONS.filter((r) => r.proOnly).map((r) => r.value)
    expect(proOnly).toEqual(["1080p", "4k"])
  })

  it("every preset carries non-empty prompt seed text", () => {
    for (const p of VIDEO_STYLE_PRESETS) {
      expect(p.prompt.length).toBeGreaterThan(0)
    }
    expect(presetLabel("lyric_video")).toBe("Lyric Video")
  })
})

describe("estimateVideoCost", () => {
  // Mirrors src/acemusic/api/services/credits.py get_video_cost.
  it("bills the base rate per resolution", () => {
    expect(estimateVideoCost("720p", 60)).toBe(5)
    expect(estimateVideoCost("1080p", 60)).toBe(7)
    expect(estimateVideoCost("4k", 60)).toBe(8)
  })

  it("adds the long-duration surcharge past 180s, capped at 10", () => {
    expect(estimateVideoCost("720p", 181)).toBe(7)
    expect(estimateVideoCost("1080p", 300)).toBe(9)
    expect(estimateVideoCost("4k", 300)).toBe(10) // 8 + 2 = 10, at the cap
  })

  it("bills the base rate when duration is unknown or at the boundary", () => {
    expect(estimateVideoCost("720p", null)).toBe(5)
    expect(estimateVideoCost("720p", 180)).toBe(5)
  })
})

describe("submitVideoJob", () => {
  it("posts the config with the clip id and classifies 202 as accepted", async () => {
    const fetchSpy = mockFetch(202, { job_id: "j1", status: "queued" })
    const result = await submitVideoJob("c1", config, "tok")
    expect(result).toEqual({ status: "accepted", jobId: "j1" })
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/videos/generate")
    expect(init?.headers).toMatchObject({ authorization: "Bearer tok" })
    const body = JSON.parse(String(init?.body))
    expect(body).toMatchObject({ clip_id: "c1", prompt: "neon city", resolution: "720p" })
    // Optional fields that are unset must not be sent (extra="forbid" upstream
    // is fine with them, but null would 422).
    expect(body).not.toHaveProperty("style_preset")
  })

  it("classifies 401 as unauthorized", async () => {
    mockFetch(401, { detail: "Not authenticated." })
    expect(await submitVideoJob("c1", config, "tok")).toEqual({
      status: "unauthorized",
    })
  })

  it("classifies 402 with the balance payload", async () => {
    mockFetch(402, {
      detail: { error: "insufficient_credits", balance: 2, required: 5 },
    })
    expect(await submitVideoJob("c1", config, "tok")).toEqual({
      status: "insufficient_credits",
      balance: 2,
      required: 5,
    })
  })

  it("classifies 422 as invalid with the detail message", async () => {
    mockFetch(422, { detail: [{ msg: "Provide a style prompt or a style_preset" }] })
    expect(await submitVideoJob("c1", config, "tok")).toEqual({
      status: "invalid",
      detail: "Provide a style prompt or a style_preset",
    })
  })

  it("classifies 503 as unavailable (video not configured)", async () => {
    mockFetch(503, { detail: "Video generation is not configured on this deployment." })
    expect(await submitVideoJob("c1", config, "tok")).toEqual({
      status: "unavailable",
      detail: "Video generation is not configured on this deployment.",
    })
  })

  it("classifies a network failure as error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"))
    const result = await submitVideoJob("c1", config, "tok")
    expect(result.status).toBe("error")
  })
})

describe("fetchVideoStatus", () => {
  it("classifies queued/rendering/encoding as pending", async () => {
    for (const status of ["queued", "rendering", "encoding"] as const) {
      mockFetch(200, { job_id: "j1", status, progress: 40 })
      const result = await fetchVideoStatus("j1", "tok")
      expect(result).toMatchObject({ kind: "pending" })
      vi.restoreAllMocks()
    }
  })

  it("classifies complete with the detail (video id)", async () => {
    mockFetch(200, { job_id: "j1", status: "complete", progress: 100, video_id: "v1" })
    expect(await fetchVideoStatus("j1", "tok")).toEqual({
      kind: "complete",
      detail: { job_id: "j1", status: "complete", progress: 100, video_id: "v1" },
    })
  })

  it("classifies failed with the error message", async () => {
    mockFetch(200, { job_id: "j1", status: "failed", progress: 0, error: "render died" })
    expect(await fetchVideoStatus("j1", "tok")).toEqual({
      kind: "failed",
      error: "render died",
    })
  })

  it("classifies 401 as unauthorized and other 4xx as failed", async () => {
    mockFetch(401, {})
    expect(await fetchVideoStatus("j1", "tok")).toEqual({ kind: "unauthorized" })
    vi.restoreAllMocks()
    mockFetch(404, { detail: "Video job not found." })
    expect((await fetchVideoStatus("j1", "tok")).kind).toBe("failed")
  })

  it("classifies 5xx and network errors as transient", async () => {
    mockFetch(502, {})
    expect(await fetchVideoStatus("j1", "tok")).toEqual({ kind: "transient" })
    vi.restoreAllMocks()
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"))
    expect(await fetchVideoStatus("j1", "tok")).toEqual({ kind: "transient" })
  })
})
