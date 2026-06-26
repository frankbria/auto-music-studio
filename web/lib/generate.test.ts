import { afterEach, describe, expect, it, vi } from "vitest"

import { buildGenerationPayload, submitGeneration } from "@/lib/generate"

afterEach(() => vi.restoreAllMocks())

describe("buildGenerationPayload", () => {
  it("maps description to prompt and joins tags into style", () => {
    const payload = buildGenerationPayload({
      description: "  a dreamy track  ",
      lyrics: "",
      instrumental: true,
      selectedTags: ["lo-fi", "ambient"],
    })
    expect(payload).toEqual({
      prompt: "a dreamy track",
      style: "lo-fi, ambient",
      instrumental: true,
    })
  })

  it("omits style and lyrics when empty", () => {
    const payload = buildGenerationPayload({
      description: "just a beat",
      lyrics: "   ",
      instrumental: false,
      selectedTags: [],
    })
    expect(payload).toEqual({ prompt: "just a beat", instrumental: false })
    expect(payload).not.toHaveProperty("style")
    expect(payload).not.toHaveProperty("lyrics")
  })

  it("falls back to lyrics for the prompt when description is empty", () => {
    const payload = buildGenerationPayload({
      description: "",
      lyrics: "first line\nsecond line",
      instrumental: false,
      selectedTags: [],
    })
    expect(payload.prompt).toBe("first line\nsecond line")
    expect(payload.lyrics).toBe("first line\nsecond line")
  })
})

describe("submitGeneration", () => {
  const data = {
    description: "song",
    lyrics: "",
    instrumental: false,
    selectedTags: [],
  }

  it("returns the job id on 202 and sends the Bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job-123", status: "queued" }), {
        status: 202,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const result = await submitGeneration(data, "tok")
    expect(result).toEqual({ status: "accepted", jobId: "job-123" })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/generate")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(JSON.parse(opts.body)).toEqual({ prompt: "song", instrumental: false })
  })

  it("classifies a 401 as unauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 }))
    )
    expect(await submitGeneration(data, "tok")).toEqual({
      status: "unauthorized",
    })
  })

  it("surfaces a 422 validation message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: [{ msg: "prompt too long" }] }), {
          status: 422,
        })
      )
    )
    expect(await submitGeneration(data, "tok")).toEqual({
      status: "invalid",
      detail: "prompt too long",
    })
  })

  it("returns a generic error on other failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 500 }))
    )
    const result = await submitGeneration(data, "tok")
    expect(result.status).toBe("error")
  })

  it("returns an error result when the request rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")))
    const result = await submitGeneration(data, "tok")
    expect(result.status).toBe("error")
  })
})
