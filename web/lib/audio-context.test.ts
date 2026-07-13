import { afterEach, describe, expect, it, vi } from "vitest"

import { getAudioContextCtor } from "./audio-context"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("getAudioContextCtor", () => {
  it("returns window.AudioContext when present", () => {
    class FakeAudioContext {}
    vi.stubGlobal("AudioContext", FakeAudioContext)
    expect(getAudioContextCtor()).toBe(FakeAudioContext)
  })

  it("falls back to the vendor-prefixed webkitAudioContext (Safari) when AudioContext is absent", () => {
    vi.stubGlobal("AudioContext", undefined)
    class FakeWebkitAudioContext {}
    vi.stubGlobal("webkitAudioContext", FakeWebkitAudioContext)
    expect(getAudioContextCtor()).toBe(FakeWebkitAudioContext)
  })

  it("returns undefined when neither global exists", () => {
    vi.stubGlobal("AudioContext", undefined)
    vi.stubGlobal("webkitAudioContext", undefined)
    expect(getAudioContextCtor()).toBeUndefined()
  })
})
