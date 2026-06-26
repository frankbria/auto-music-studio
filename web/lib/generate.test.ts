import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildAdvancedPayload,
  buildGenerationPayload,
  buildSoundsPayload,
  submitGeneration,
  validateAdvanced,
  validateSounds,
  type AdvancedFormData,
  type SoundsFormData,
} from "@/lib/generate"

afterEach(() => vi.restoreAllMocks())

/** A valid baseline; individual tests override only what they exercise. */
function advancedData(overrides: Partial<AdvancedFormData> = {}): AdvancedFormData {
  return {
    lyrics: "",
    lyricsMode: "manual",
    vocalLanguage: "",
    styles: "",
    selectedTags: [],
    instrumental: false,
    bpmAuto: true,
    bpm: "",
    key: "",
    timeSignature: "",
    duration: "",
    weirdness: 50,
    styleInfluence: 50,
    seedRandom: true,
    seed: "",
    ...overrides,
  }
}

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

describe("buildAdvancedPayload", () => {
  it("combines free-text styles and tags into the style string and prompt", () => {
    const payload = buildAdvancedPayload(
      advancedData({ styles: "cinematic, epic", selectedTags: ["lo-fi", "ambient"] })
    )
    expect(payload.style).toBe("cinematic, epic, lo-fi, ambient")
    // With no description field, the combined style string becomes the prompt.
    expect(payload.prompt).toBe("cinematic, epic, lo-fi, ambient")
  })

  it("falls back to lyrics for the prompt when no styles are given (manual mode)", () => {
    const payload = buildAdvancedPayload(
      advancedData({ lyricsMode: "manual", lyrics: "[Verse]\nhello" })
    )
    expect(payload.prompt).toBe("[Verse]\nhello")
    expect(payload.lyrics).toBe("[Verse]\nhello")
  })

  it("omits lyrics entirely in auto mode", () => {
    const payload = buildAdvancedPayload(
      advancedData({ styles: "jazz", lyricsMode: "auto", lyrics: "ignored" })
    )
    expect(payload).not.toHaveProperty("lyrics")
  })

  it("omits bpm when Auto is on, and sends the number otherwise", () => {
    expect(
      buildAdvancedPayload(advancedData({ styles: "rock", bpmAuto: true }))
    ).not.toHaveProperty("bpm")
    expect(
      buildAdvancedPayload(advancedData({ styles: "rock", bpmAuto: false, bpm: "120" })).bpm
    ).toBe(120)
  })

  it("includes key, time_signature, duration, vocal_language, weirdness, style_influence and numeric seed", () => {
    const payload = buildAdvancedPayload(
      advancedData({
        styles: "orchestral",
        vocalLanguage: "English",
        key: "C major",
        timeSignature: "3/4",
        duration: "90",
        weirdness: 70,
        styleInfluence: 30,
        seedRandom: false,
        seed: "42",
      })
    )
    expect(payload).toMatchObject({
      vocal_language: "English",
      key: "C major",
      time_signature: "3/4",
      duration: 90,
      weirdness: 70,
      style_influence: 30,
      seed: 42,
    })
  })

  it("caps the lyrics-derived prompt at the backend's prompt limit", () => {
    // Lyrics may be up to 5000 chars but prompt is capped at 2000; a lyrics-only
    // submission must not build an over-long prompt that the backend would 422.
    const payload = buildAdvancedPayload(
      advancedData({ styles: "", lyricsMode: "manual", lyrics: "x".repeat(5000) })
    )
    expect(payload.prompt.length).toBe(2000)
    expect(payload.lyrics).toHaveLength(5000)
  })

  it("omits seed when Random is selected", () => {
    const payload = buildAdvancedPayload(
      advancedData({ styles: "rock", seedRandom: true, seed: "42" })
    )
    expect(payload).not.toHaveProperty("seed")
  })

  it("never sends UI-only fields (backend forbids unknown keys)", () => {
    const payload = buildAdvancedPayload(advancedData({ styles: "rock" }))
    expect(payload).not.toHaveProperty("vocal_gender")
    expect(payload).not.toHaveProperty("exclude_styles")
    expect(payload).not.toHaveProperty("song_title")
    expect(payload).not.toHaveProperty("workspace")
  })
})

describe("validateAdvanced", () => {
  it("accepts a valid form", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", bpmAuto: false, bpm: "120" }))).toBeNull()
  })

  it("requires a style or lyrics", () => {
    expect(validateAdvanced(advancedData())).toMatch(/style or lyrics/i)
  })

  it("rejects an out-of-range BPM", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", bpmAuto: false, bpm: "300" }))).toMatch(
      /bpm/i
    )
    expect(validateAdvanced(advancedData({ styles: "rock", bpmAuto: false, bpm: "10" }))).toMatch(
      /bpm/i
    )
  })

  it("ignores BPM bounds when Auto is on", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", bpmAuto: true, bpm: "300" }))).toBeNull()
  })

  it("rejects an out-of-range duration", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", duration: "5" }))).toMatch(/duration/i)
    expect(validateAdvanced(advancedData({ styles: "rock", duration: "999" }))).toMatch(/duration/i)
  })

  it("rejects an over-long key", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", key: "x".repeat(60) }))).toMatch(/key/i)
  })

  it("rejects out-of-range weirdness and style influence", () => {
    expect(validateAdvanced(advancedData({ styles: "rock", weirdness: 200 }))).toMatch(/weirdness/i)
    expect(validateAdvanced(advancedData({ styles: "rock", styleInfluence: -1 }))).toMatch(
      /influence/i
    )
  })
})

/** A valid baseline sounds form; tests override only what they exercise. */
function soundsData(overrides: Partial<SoundsFormData> = {}): SoundsFormData {
  return {
    description: "a punchy kick",
    soundType: "one-shot",
    bpmAuto: true,
    bpm: "",
    key: "",
    ...overrides,
  }
}

describe("buildSoundsPayload", () => {
  it("maps description to prompt and fixes mode to sound (instrumental)", () => {
    const payload = buildSoundsPayload(soundsData({ description: "  warm pad  " }))
    expect(payload).toMatchObject({
      prompt: "warm pad",
      mode: "sound",
      sound_type: "one-shot",
      instrumental: true,
    })
  })

  it("never sends bpm or key for a one-shot (backend forbids them)", () => {
    // Even if stray loop values are present, a one-shot must omit tempo/tonal keys.
    const payload = buildSoundsPayload(
      soundsData({ soundType: "one-shot", bpmAuto: false, bpm: "120", key: "C major" })
    )
    expect(payload).not.toHaveProperty("bpm")
    expect(payload).not.toHaveProperty("key")
  })

  it("sends bpm and key for a loop", () => {
    const payload = buildSoundsPayload(
      soundsData({ soundType: "loop", bpmAuto: false, bpm: "128", key: "A minor" })
    )
    expect(payload).toMatchObject({ sound_type: "loop", bpm: 128, key: "A minor" })
  })

  it("omits bpm for a loop when Auto is on, and key when Any", () => {
    const payload = buildSoundsPayload(
      soundsData({ soundType: "loop", bpmAuto: true, bpm: "128", key: "" })
    )
    expect(payload).not.toHaveProperty("bpm")
    expect(payload).not.toHaveProperty("key")
  })
})

describe("validateSounds", () => {
  it("accepts a valid one-shot and a valid loop", () => {
    expect(validateSounds(soundsData())).toBeNull()
    expect(
      validateSounds(soundsData({ soundType: "loop", bpmAuto: false, bpm: "120" }))
    ).toBeNull()
  })

  it("requires a sound type", () => {
    expect(validateSounds(soundsData({ soundType: "" }))).toMatch(/type/i)
  })

  it("requires a description", () => {
    expect(validateSounds(soundsData({ description: "  " }))).toMatch(/description/i)
  })

  it("rejects an over-long description (the prompt bound)", () => {
    expect(validateSounds(soundsData({ description: "x".repeat(2001) }))).toMatch(
      /description/i
    )
  })

  it("rejects an out-of-range loop BPM", () => {
    expect(
      validateSounds(soundsData({ soundType: "loop", bpmAuto: false, bpm: "300" }))
    ).toMatch(/bpm/i)
  })

  it("ignores BPM bounds when Auto is on", () => {
    expect(
      validateSounds(soundsData({ soundType: "loop", bpmAuto: true, bpm: "300" }))
    ).toBeNull()
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

  it("treats a 202 with no job id as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 202 }))
    )
    const result = await submitGeneration(data, "tok")
    expect(result.status).toBe("error")
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
