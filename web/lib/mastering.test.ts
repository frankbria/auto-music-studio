import { afterEach, describe, expect, it, vi } from "vitest"

import {
  approveMasteringPreview,
  fetchMasteringHistory,
  fetchMasteringPreviews,
  fetchMasteringStatus,
  masteredHref,
  masteringDisplayStatus,
  submitMasteringJob,
  type MasteringConfig,
  type MasteringHistoryItem,
} from "@/lib/mastering"

const config: MasteringConfig = {
  profile: "streaming",
  service: "dolby",
  format: "wav",
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => vi.restoreAllMocks())

describe("submitMasteringJob", () => {
  it("POSTs clip_id + config with the Bearer token and returns the job id on 202", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonRes({ job_id: "j1", status: "queued" }, 202))
    vi.stubGlobal("fetch", fetchMock)

    const result = await submitMasteringJob("c1", config, "tok")

    expect(result).toEqual({ status: "accepted", jobId: "j1" })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/mastering/jobs")
    expect(opts.method).toBe("POST")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(JSON.parse(opts.body)).toEqual({
      clip_id: "c1",
      profile: "streaming",
      service: "dolby",
      format: "wav",
    })
  })

  it("classifies 401 as unauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "no" }, 401))
    )
    expect(await submitMasteringJob("c1", config, "tok")).toEqual({
      status: "unauthorized",
    })
  })

  it("classifies 402 as insufficient_credits with balance/required", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonRes(
            {
              detail: {
                error: "insufficient_credits",
                balance: 1,
                required: 3,
              },
            },
            402
          )
        )
    )
    expect(await submitMasteringJob("c1", config, "tok")).toEqual({
      status: "insufficient_credits",
      balance: 1,
      required: 3,
    })
  })

  it("classifies 422 as invalid with the message", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonRes({ detail: [{ msg: "target_lufs is required" }] }, 422)
        )
    )
    expect(
      await submitMasteringJob("c1", { ...config, profile: "custom" }, "tok")
    ).toEqual({
      status: "invalid",
      detail: "target_lufs is required",
    })
  })

  it("returns error on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    expect((await submitMasteringJob("c1", config, "tok")).status).toBe("error")
  })
})

describe("fetchMasteringStatus", () => {
  it("classifies completed and carries the detail", async () => {
    const detail = { job_id: "j1", status: "completed", mastered_clip_id: "m1" }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(detail)))
    const result = await fetchMasteringStatus("j1", "tok")
    expect(result.kind).toBe("completed")
    if (result.kind === "completed")
      expect(result.detail.mastered_clip_id).toBe("m1")
  })

  it("classifies queued/processing as pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ job_id: "j1", status: "processing" }))
    )
    expect((await fetchMasteringStatus("j1", "tok")).kind).toBe("pending")
  })

  it("classifies failed with the backend error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ status: "failed", error: "boom" }))
    )
    expect(await fetchMasteringStatus("j1", "tok")).toEqual({
      kind: "failed",
      error: "boom",
    })
  })

  it("treats a 404 as terminal failure, not transient", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "gone" }, 404))
    )
    expect((await fetchMasteringStatus("j1", "tok")).kind).toBe("failed")
  })

  it("treats 5xx and network errors as transient", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 503)))
    expect((await fetchMasteringStatus("j1", "tok")).kind).toBe("transient")
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")))
    expect((await fetchMasteringStatus("j1", "tok")).kind).toBe("transient")
  })

  it("classifies 401 as unauthorized", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 401)))
    expect((await fetchMasteringStatus("j1", "tok")).kind).toBe("unauthorized")
  })
})

describe("fetchMasteringPreviews", () => {
  it("returns the preview set on success", async () => {
    const previews = { previews: [{ preview_id: "m1", audio_url: "u" }] }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(previews)))
    expect(await fetchMasteringPreviews("j1", "tok")).toEqual(previews)
  })

  it("returns null on error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 404)))
    expect(await fetchMasteringPreviews("j1", "tok")).toBeNull()
  })
})

describe("fetchMasteringHistory", () => {
  it("GETs the clip's jobs with the Bearer token and returns them", async () => {
    const jobs = [{ job_id: "j1", status: "queued", is_approved: false }]
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ jobs }))
    vi.stubGlobal("fetch", fetchMock)

    expect(await fetchMasteringHistory("c 1", "tok")).toEqual(jobs)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/mastering/jobs?clip_id=c%201")
    expect(opts.headers.authorization).toBe("Bearer tok")
  })

  it("returns null on an error status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 500)))
    expect(await fetchMasteringHistory("c1", "tok")).toBeNull()
  })

  it("returns null when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")))
    expect(await fetchMasteringHistory("c1", "tok")).toBeNull()
  })
})

function historyItem(
  over: Partial<MasteringHistoryItem>
): MasteringHistoryItem {
  return { job_id: "j", status: "completed", is_approved: false, ...over }
}

describe("masteringDisplayStatus", () => {
  it("splits completed into preview_ready vs approved", () => {
    expect(masteringDisplayStatus(historyItem({ is_approved: false }))).toBe(
      "preview_ready"
    )
    expect(masteringDisplayStatus(historyItem({ is_approved: true }))).toBe(
      "approved"
    )
  })

  it("passes through the transient/failed states", () => {
    expect(masteringDisplayStatus(historyItem({ status: "queued" }))).toBe(
      "queued"
    )
    expect(masteringDisplayStatus(historyItem({ status: "processing" }))).toBe(
      "processing"
    )
    expect(masteringDisplayStatus(historyItem({ status: "failed" }))).toBe(
      "failed"
    )
  })
})

describe("masteredHref", () => {
  it("links an approved master to its song page", () => {
    expect(
      masteredHref(historyItem({ is_approved: true, mastered_clip_id: "m1" }))
    ).toBe("/song/m1")
  })

  it("returns null for unapproved or clip-less jobs", () => {
    expect(masteredHref(historyItem({ mastered_clip_id: "m1" }))).toBeNull()
    expect(masteredHref(historyItem({ is_approved: true }))).toBeNull()
  })
})

describe("approveMasteringPreview", () => {
  it("POSTs the preview id and returns the promoted clip", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonRes({ clip_id: "m1", audio_url: "u" }))
    vi.stubGlobal("fetch", fetchMock)

    const result = await approveMasteringPreview("j1", "m1", "tok")

    expect(result).toEqual({ status: "approved", clipId: "m1", audioUrl: "u" })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/mastering/jobs/j1/approve")
    expect(JSON.parse(opts.body)).toEqual({ preview_id: "m1" })
  })

  it("classifies 401 as unauthorized", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 401)))
    expect((await approveMasteringPreview("j1", "m1", "tok")).status).toBe(
      "unauthorized"
    )
  })

  it("returns error on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "gone" }, 404))
    )
    expect((await approveMasteringPreview("j1", "m1", "tok")).status).toBe(
      "error"
    )
  })
})
