import { describe, expect, it } from "vitest"

import { clipAudioUrl, clipArtworkUrl, formatTime } from "@/lib/clips"

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
