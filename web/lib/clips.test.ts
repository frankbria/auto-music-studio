import { afterEach, describe, expect, it, vi } from "vitest"

import {
  clipAudioUrl,
  clipArtworkUrl,
  downloadClipAudio,
  formatTime,
} from "@/lib/clips"

describe("clip url builders", () => {
  it("builds the audio + artwork backend paths", () => {
    expect(clipAudioUrl("abc")).toBe("/api/v1/clips/abc/audio")
    expect(clipArtworkUrl("abc")).toBe("/api/v1/clips/abc/artwork")
  })

  it("encodes ids with unsafe characters", () => {
    expect(clipAudioUrl("a/b?c")).toBe("/api/v1/clips/a%2Fb%3Fc/audio")
  })
})

describe("formatTime", () => {
  it("formats minutes and zero-padded seconds", () => {
    expect(formatTime(0)).toBe("0:00")
    expect(formatTime(5)).toBe("0:05")
    expect(formatTime(65)).toBe("1:05")
    expect(formatTime(605)).toBe("10:05")
  })

  it("floors fractional seconds and clamps invalid input", () => {
    expect(formatTime(9.9)).toBe("0:09")
    expect(formatTime(-3)).toBe("0:00")
    expect(formatTime(NaN)).toBe("0:00")
  })
})

describe("downloadClipAudio", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubDownloadEnv(status = 200) {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(new Uint8Array([1, 2]), { status }))
    vi.stubGlobal("fetch", fetchMock)
    // jsdom has no createObjectURL; give it one so the anchor gets a real href.
    const createUrl = vi.fn().mockReturnValue("blob:test")
    const revokeUrl = vi.fn()
    vi.stubGlobal("URL", Object.assign(URL, {}))
    URL.createObjectURL = createUrl
    URL.revokeObjectURL = revokeUrl
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {})
    return { fetchMock, createUrl, revokeUrl, click }
  }

  it("fetches the BFF audio route with the token and clicks a named anchor", async () => {
    const { fetchMock, click, revokeUrl } = stubDownloadEnv()
    const anchors: HTMLAnchorElement[] = []
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = origCreate(tag)
      if (tag === "a") anchors.push(el as HTMLAnchorElement)
      return el
    })

    const ok = await downloadClipAudio("c1", "mp3", "tok", "My Song")
    expect(ok).toBe(true)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/audio?format=mp3")
    expect(
      (opts.headers as Record<string, string>).authorization
    ).toBe("Bearer tok")

    expect(anchors).toHaveLength(1)
    expect(anchors[0].download).toBe("My Song.mp3")
    expect(click).toHaveBeenCalledOnce()
    expect(revokeUrl).toHaveBeenCalledWith("blob:test")
  })

  it("falls back to the clip id for an untitled clip", async () => {
    stubDownloadEnv()
    const anchors: HTMLAnchorElement[] = []
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = origCreate(tag)
      if (tag === "a") anchors.push(el as HTMLAnchorElement)
      return el
    })

    await downloadClipAudio("c1", "wav", "tok", null)
    expect(anchors[0].download).toBe("c1.wav")
  })

  it("returns false without downloading when the fetch fails", async () => {
    const { click } = stubDownloadEnv(404)
    const ok = await downloadClipAudio("c1", "mp3", "tok", "x")
    expect(ok).toBe(false)
    expect(click).not.toHaveBeenCalled()
  })

  it("returns false when the request throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net down")))
    const ok = await downloadClipAudio("c1", "mp3", "tok", "x")
    expect(ok).toBe(false)
  })
})
