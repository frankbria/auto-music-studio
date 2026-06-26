import { describe, expect, it } from "vitest"

import {
  validateBio,
  validateDisplayName,
  validateHandle,
  validateNewStyleTag,
  STYLE_TAGS_MAX_ITEMS,
} from "@/lib/profile"

describe("validateDisplayName", () => {
  it("accepts a normal name", () => {
    expect(validateDisplayName("Ada Lovelace")).toBeNull()
  })
  it("requires a non-empty value", () => {
    expect(validateDisplayName("   ")).toMatch(/required/)
  })
  it("rejects names over 100 chars", () => {
    expect(validateDisplayName("a".repeat(101))).toMatch(/at most/)
  })
})

describe("validateHandle", () => {
  it("treats empty as valid (unclaimed)", () => {
    expect(validateHandle("")).toBeNull()
  })
  it("accepts alphanumeric + internal hyphens", () => {
    expect(validateHandle("ada-lovelace1")).toBeNull()
  })
  it("rejects too-short handles", () => {
    expect(validateHandle("ab")).toMatch(/3-30/)
  })
  it("rejects too-long handles", () => {
    expect(validateHandle("a".repeat(31))).toMatch(/3-30/)
  })
  it("rejects disallowed characters", () => {
    expect(validateHandle("ada_lovelace")).toMatch(/letters, numbers/)
  })
  it("rejects leading/trailing hyphens", () => {
    expect(validateHandle("-ada")).toMatch(/hyphen/)
    expect(validateHandle("ada-")).toMatch(/hyphen/)
  })
})

describe("validateBio", () => {
  it("accepts within limit", () => {
    expect(validateBio("hello")).toBeNull()
  })
  it("rejects over 500 chars", () => {
    expect(validateBio("a".repeat(501))).toMatch(/at most/)
  })
  it("ignores surrounding whitespace when checking the limit", () => {
    expect(validateBio("  " + "a".repeat(500) + "  ")).toBeNull()
  })
})

describe("validateNewStyleTag", () => {
  it("accepts a fresh tag", () => {
    expect(validateNewStyleTag("cello", [])).toBeNull()
  })
  it("trims and rejects empty", () => {
    expect(validateNewStyleTag("   ", [])).toMatch(/empty/)
  })
  it("rejects duplicates case-insensitively", () => {
    expect(validateNewStyleTag("Cello", ["cello"])).toMatch(/already/)
  })
  it("rejects tags over 30 chars", () => {
    expect(validateNewStyleTag("a".repeat(31), [])).toMatch(/at most/)
  })
  it("rejects when the list is full", () => {
    const full = Array.from({ length: STYLE_TAGS_MAX_ITEMS }, (_, i) => `t${i}`)
    expect(validateNewStyleTag("more", full)).toMatch(/At most/)
  })
})
