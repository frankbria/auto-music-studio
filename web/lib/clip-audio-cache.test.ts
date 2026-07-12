import { afterEach, describe, expect, it, vi } from "vitest"

import { getClipAudio } from "./clip-audio-cache"

function fakeBuffer(length: number, sampleRate = 44100): AudioBuffer {
  const data = new Float32Array(length).fill(0.5)
  return {
    numberOfChannels: 1,
    length,
    sampleRate,
    duration: length / sampleRate,
    getChannelData: () => data,
  } as unknown as AudioBuffer
}

// A fresh Response per call — its body stream can only be read once, so
// mockResolvedValue (which reuses one instance) breaks a second real fetch.
function jsonResponse(status: number) {
  return vi.fn(() =>
    Promise.resolve(new Response(new ArrayBuffer(8), { status }))
  )
}

function stubAudioContext(decodeAudioData = vi.fn()) {
  class FakeAudioContext {
    close = vi.fn().mockResolvedValue(undefined)
    decodeAudioData = decodeAudioData
  }
  vi.stubGlobal("AudioContext", FakeAudioContext)
  return decodeAudioData
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("getClipAudio", () => {
  it("fetches and decodes a clip's audio, keeping the buffer and downsampled peaks", async () => {
    const decodeAudioData = vi.fn().mockResolvedValue(fakeBuffer(1000))
    stubAudioContext(decodeAudioData)
    const fetchMock = jsonResponse(200)
    vi.stubGlobal("fetch", fetchMock)

    const result = await getClipAudio("clip-a", "tok")
    expect(result.buffer.length).toBe(1000)
    expect(result.duration).toBeCloseTo(1000 / 44100)
    expect(result.peaks.length).toBeGreaterThan(0)
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/clips/clip-a/audio",
      expect.objectContaining({ headers: { authorization: "Bearer tok" } })
    )
  })

  it("caches by clip id — a second call does not refetch", async () => {
    const decodeAudioData = vi.fn().mockResolvedValue(fakeBuffer(500))
    stubAudioContext(decodeAudioData)
    const fetchMock = jsonResponse(200)
    vi.stubGlobal("fetch", fetchMock)

    await getClipAudio("clip-b", "tok")
    await getClipAudio("clip-b", "tok")
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("fetches independently for different clip ids", async () => {
    stubAudioContext(vi.fn().mockResolvedValue(fakeBuffer(100)))
    const fetchMock = jsonResponse(200)
    vi.stubGlobal("fetch", fetchMock)

    await getClipAudio("clip-d1", "tok")
    await getClipAudio("clip-d2", "tok")
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("evicts a failed decode so a later call can retry", async () => {
    const fetchMock = jsonResponse(500)
    vi.stubGlobal("fetch", fetchMock)
    stubAudioContext()

    await expect(getClipAudio("clip-c", "tok")).rejects.toThrow()

    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response(new ArrayBuffer(8), { status: 200 }))
    )
    stubAudioContext(vi.fn().mockResolvedValue(fakeBuffer(10)))
    const result = await getClipAudio("clip-c", "tok")
    expect(result.buffer.length).toBe(10)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
