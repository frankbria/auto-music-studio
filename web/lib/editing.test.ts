import { afterEach, describe, expect, it, vi } from "vitest"

import {
  submitCrop,
  submitMashup,
  submitRemaster,
  submitSample,
  submitSpeed,
} from "@/lib/editing"

afterEach(() => vi.restoreAllMocks())

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

describe("submitCrop", () => {
  it("POSTs to the crop route with the bearer token and returns the job", async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ job_id: "job-1", status: "queued" }), {
        status: 202,
      })
    )

    const result = await submitCrop(
      "clip-abc",
      { start: "0s", end: "30s" },
      "tok"
    )

    expect(result).toEqual({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 0,
    })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/clip-abc/crop")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({ start: "0s", end: "30s" })
  })

  it("drops empty-string and undefined optionals from the payload", async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ job_id: "j" }), { status: 202 })
    )
    await submitCrop(
      "c",
      { start: "0s", end: "10s", fade_in: "", fade_out: undefined, snap_to_beat: true },
      "tok"
    )
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      start: "0s",
      end: "10s",
      snap_to_beat: true,
    })
  })
})

describe("submitSpeed", () => {
  it("carries the estimated time from an iterative-style 202", async () => {
    stubFetch(
      new Response(
        JSON.stringify({ job_id: "j2", status: "queued", estimated_time_seconds: 45 }),
        { status: 202 }
      )
    )
    const result = await submitSpeed("c", { multiplier: 1.5 }, "tok")
    expect(result).toEqual({ status: "accepted", jobId: "j2", estimatedSeconds: 45 })
  })
})

describe("submitSample", () => {
  it("maps a 402 into an insufficientCredits result", async () => {
    stubFetch(
      new Response(
        JSON.stringify({
          detail: { error: "insufficient_credits", balance: 2, required: 4 },
        }),
        { status: 402 }
      )
    )
    const result = await submitSample(
      "c",
      { start: "0s", end: "5s", role: "loop-bed", prompt: "warm", num_clips: 4 },
      "tok"
    )
    expect(result).toEqual({ status: "insufficientCredits", balance: 2, required: 4 })
  })
})

describe("submitRemaster", () => {
  it("classifies 401 as unauthorized", async () => {
    stubFetch(new Response("{}", { status: 401 }))
    expect(await submitRemaster("c", {}, "tok")).toEqual({ status: "unauthorized" })
  })

  it("classifies 422 as invalid with the field message", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: [{ msg: "unsupported format" }] }), {
        status: 422,
      })
    )
    expect(await submitRemaster("c", {}, "tok")).toEqual({
      status: "invalid",
      detail: "unsupported format",
    })
  })

  it("returns an error result when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    const result = await submitRemaster("c", {}, "tok")
    expect(result.status).toBe("error")
  })

  it("treats a 202 with no job id as an error", async () => {
    stubFetch(new Response("{}", { status: 202 }))
    const result = await submitRemaster("c", {}, "tok")
    expect(result.status).toBe("error")
  })
})

describe("submitMashup", () => {
  it("POSTs the ordered clip ids to the mashup route", async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ job_id: "m1", estimated_time_seconds: 45 }), {
        status: 202,
      })
    )
    await submitMashup({ clip_ids: ["a", "b"], blend_mode: "layered" }, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/mashup")
    expect(JSON.parse(opts.body)).toEqual({
      clip_ids: ["a", "b"],
      blend_mode: "layered",
    })
  })
})

import { saveClipVersion } from "@/lib/editing"

describe("saveClipVersion", () => {
  const wav = () => new Blob([new Uint8Array([1, 2, 3])], { type: "audio/wav" })

  it("uploads the WAV + metadata as multipart to the version route and returns the job", async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ job_id: "v1", status: "queued" }), { status: 202 })
    )

    const result = await saveClipVersion(
      "clip-xyz",
      wav(),
      { title: "  Radio edit  ", operations: [{ kind: "delete", startSec: 1, endSec: 2 }] },
      "tok"
    )

    expect(result).toEqual({ status: "accepted", jobId: "v1", estimatedSeconds: 0 })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/clip-xyz/version")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    // No explicit content-type: the browser sets multipart + boundary itself.
    expect(opts.headers["content-type"]).toBeUndefined()

    const form = opts.body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect(form.get("title")).toBe("Radio edit") // trimmed
    expect(JSON.parse(form.get("operations") as string)).toEqual([
      { kind: "delete", startSec: 1, endSec: 2 },
    ])
    expect(form.get("file")).toBeInstanceOf(Blob)
  })

  it("omits a blank title", async () => {
    const fetchMock = stubFetch(new Response("{}", { status: 202 }))
    await saveClipVersion("c", wav(), { title: "   ", operations: [] }, "tok")
    const form = fetchMock.mock.calls[0][1].body as FormData
    expect(form.get("title")).toBeNull()
  })

  it("classifies a 404 (endpoint not yet deployed) as an error result", async () => {
    stubFetch(new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }))
    const result = await saveClipVersion("c", wav(), { operations: [] }, "tok")
    expect(result).toEqual({ status: "error", detail: "Not Found" })
  })

  it("returns an error result when the network throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    const result = await saveClipVersion("c", wav(), { operations: [] }, "tok")
    expect(result.status).toBe("error")
  })
})
