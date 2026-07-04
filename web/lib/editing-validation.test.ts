import { describe, expect, it } from "vitest"

import {
  formatMs,
  parseTimeString,
  validateRange,
  validateTimeField,
} from "@/lib/editing-validation"

describe("parseTimeString", () => {
  it.each([
    ["30s", 30000],
    ["1m30s", 90000],
    ["1.5s", 1500],
    ["90s", 90000],
    ["5", 5000],
    ["2m0s", 120000],
    ["  45s  ", 45000],
  ])("parses %s to %d ms", (input, expected) => {
    expect(parseTimeString(input)).toBe(expected)
  })

  it.each(["", "1m", "1m30", "abc", "30sec", "-5", "s", "1:30"])(
    "returns null for invalid input %s",
    (input) => {
      expect(parseTimeString(input)).toBeNull()
    }
  )
})

describe("formatMs", () => {
  it.each([
    [45000, "45s"],
    [90000, "1m30s"],
    [120000, "2m0s"],
    [1500, "1.5s"],
    [0, "0s"],
  ])("formats %d ms as %s", (input, expected) => {
    expect(formatMs(input)).toBe(expected)
  })

  it("clamps negative/invalid input to 0s", () => {
    expect(formatMs(-100)).toBe("0s")
    expect(formatMs(NaN)).toBe("0s")
  })

  it("carries a rounded 60s remainder into the minutes place", () => {
    // 119999ms rounds to 120.00s — must render 2m0s, never 1m60s.
    expect(formatMs(119999)).toBe("2m0s")
    expect(formatMs(59999)).toBe("1m0s")
  })

  it("round-trips through parseTimeString", () => {
    expect(parseTimeString(formatMs(90000))).toBe(90000)
  })
})

describe("validateTimeField", () => {
  it("requires a value", () => {
    expect(validateTimeField("", "Duration")).toBe("Duration is required.")
    expect(validateTimeField("   ", "Duration")).toBe("Duration is required.")
  })

  it("rejects an unparseable format", () => {
    expect(validateTimeField("soon", "Duration")).toMatch(/time like/)
  })

  it("rejects a value beyond maxMs", () => {
    expect(validateTimeField("100s", "End", { maxMs: 60000 })).toMatch(
      /clip length \(1m0s\)/
    )
  })

  it("accepts a valid in-bounds value", () => {
    expect(validateTimeField("30s", "End", { maxMs: 60000 })).toBeNull()
  })
})

describe("validateRange", () => {
  it("requires start before end", () => {
    expect(validateRange("30s", "10s", 60000)).toBe("Start must be before end.")
    expect(validateRange("30s", "30s", 60000)).toBe("Start must be before end.")
  })

  it("rejects end beyond the clip duration", () => {
    expect(validateRange("10s", "100s", 60000)).toMatch(/clip length/)
  })

  it("surfaces an unparseable bound", () => {
    expect(validateRange("nope", "30s", 60000)).toMatch(/time like/)
  })

  it("accepts a valid range and tolerates unknown duration", () => {
    expect(validateRange("10s", "30s", 60000)).toBeNull()
    expect(validateRange("10s", "30s", null)).toBeNull()
  })
})
