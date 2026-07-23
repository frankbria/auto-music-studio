import { describe, expect, it } from "vitest"

import {
  masteredHref,
  masteringDisplayStatus,
  masteringHistory,
  type MasteringHistoryEntry,
} from "@/lib/mastering-history"

function entry(over: Partial<MasteringHistoryEntry>): MasteringHistoryEntry {
  return {
    id: "mj",
    songTitle: "Song",
    profile: "streaming",
    service: "dolby",
    status: "completed",
    isApproved: false,
    createdAt: "2026-07-23T00:00:00Z",
    ...over,
  }
}

describe("masteringDisplayStatus", () => {
  it("splits completed into preview_ready vs approved", () => {
    expect(masteringDisplayStatus(entry({ status: "completed", isApproved: false }))).toBe(
      "preview_ready"
    )
    expect(masteringDisplayStatus(entry({ status: "completed", isApproved: true }))).toBe(
      "approved"
    )
  })

  it("passes through the transient/failed states", () => {
    expect(masteringDisplayStatus(entry({ status: "queued" }))).toBe("queued")
    expect(masteringDisplayStatus(entry({ status: "processing" }))).toBe("processing")
    expect(masteringDisplayStatus(entry({ status: "failed" }))).toBe("failed")
  })
})

describe("masteredHref", () => {
  it("links approved masters to their song page (AC4)", () => {
    expect(masteredHref(entry({ isApproved: true, masteredClipId: "clip-neon" }))).toBe(
      "/song/clip-neon"
    )
  })

  it("returns null for unapproved or clip-less entries", () => {
    expect(masteredHref(entry({ isApproved: false }))).toBeNull()
    expect(masteredHref(entry({ isApproved: true, masteredClipId: undefined }))).toBeNull()
  })
})

describe("masteringHistory seed", () => {
  it("covers every display state and every approved row links to a clip", () => {
    const states = new Set(masteringHistory.map(masteringDisplayStatus))
    expect(states).toEqual(new Set(["approved", "preview_ready", "processing", "failed"]))
    for (const e of masteringHistory) {
      if (e.isApproved) expect(e.masteredClipId).toBeTruthy()
    }
  })
})
