import { describe, expect, it } from "vitest"

import {
  VOLUME_DB_MAX,
  VOLUME_DB_MIN,
  dbToGain,
  effectiveTrackGain,
  formatVolumeDb,
} from "@/lib/track-audio"

describe("dbToGain", () => {
  it("maps 0 dB to unity gain", () => {
    expect(dbToGain(0)).toBe(1)
  })

  it("maps +6 dB to ~2x and -6 dB to ~0.5x", () => {
    expect(dbToGain(6)).toBeCloseTo(1.995, 2)
    expect(dbToGain(-6)).toBeCloseTo(0.501, 2)
  })

  it("maps the fader floor to silence (-∞)", () => {
    expect(dbToGain(VOLUME_DB_MIN)).toBe(0)
    expect(dbToGain(VOLUME_DB_MIN - 10)).toBe(0)
  })
})

describe("effectiveTrackGain", () => {
  const track = { volumeDb: 0, muted: false, solo: false }

  it("is the volume gain when nothing is muted or soloed", () => {
    expect(effectiveTrackGain(track, false)).toBe(1)
    expect(effectiveTrackGain({ ...track, volumeDb: -6 }, false)).toBeCloseTo(
      0.501,
      2
    )
  })

  it("is 0 when the track is muted, even if it is soloed", () => {
    expect(effectiveTrackGain({ ...track, muted: true }, false)).toBe(0)
    expect(effectiveTrackGain({ ...track, muted: true, solo: true }, true)).toBe(0)
  })

  it("is 0 for non-soloed tracks while any track is soloed", () => {
    expect(effectiveTrackGain(track, true)).toBe(0)
  })

  it("is the volume gain for a soloed track while solos are active", () => {
    expect(effectiveTrackGain({ ...track, solo: true }, true)).toBe(1)
  })
})

describe("formatVolumeDb", () => {
  it("renders the floor as -∞ and other values as signed dB", () => {
    expect(formatVolumeDb(VOLUME_DB_MIN)).toBe("-∞ dB")
    expect(formatVolumeDb(0)).toBe("0 dB")
    expect(formatVolumeDb(-12)).toBe("-12 dB")
    expect(formatVolumeDb(VOLUME_DB_MAX)).toBe("+6 dB")
  })
})
