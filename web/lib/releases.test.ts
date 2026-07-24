import { describe, expect, it } from "vitest"

import {
  channelLabel,
  externalLink,
  fetchReleases,
  type ChannelDistribution,
} from "@/lib/releases"

describe("channelLabel", () => {
  it("maps known channel ids to display names", () => {
    expect(channelLabel("soundcloud")).toBe("SoundCloud")
    expect(channelLabel("landr")).toBe("LANDR")
    expect(channelLabel("distrokid")).toBe("DistroKid")
    expect(channelLabel("tunecore")).toBe("TuneCore")
  })

  it("title-cases an unknown id rather than dropping it", () => {
    expect(channelLabel("bandcamp")).toBe("Bandcamp")
  })
})

describe("externalLink", () => {
  const base: ChannelDistribution = { channel: "soundcloud", status: "live" }

  it("returns the permalink only when live and present", () => {
    expect(externalLink({ ...base, permalink: "https://x" })).toBe("https://x")
  })

  it("is null when live but no permalink", () => {
    expect(externalLink({ ...base, permalink: null })).toBeNull()
  })

  it("is null for non-live statuses even with a permalink", () => {
    expect(externalLink({ channel: "soundcloud", status: "submitted", permalink: "https://x" })).toBeNull()
  })

  it("rejects non-http(s) schemes (XSS guard) and malformed URLs", () => {
    expect(externalLink({ ...base, permalink: "javascript:alert(document.cookie)" })).toBeNull()
    expect(externalLink({ ...base, permalink: "data:text/html,<script>x</script>" })).toBeNull()
    expect(externalLink({ ...base, permalink: "not a url" })).toBeNull()
    expect(externalLink({ ...base, permalink: "http://ok" })).toBe("http://ok")
  })
})

describe("fetchReleases", () => {
  it("returns rows spanning every distribution status", async () => {
    const releases = await fetchReleases()
    const statuses = new Set(releases.flatMap((r) => r.channels.map((c) => c.status)))
    for (const s of ["draft", "ready", "submitted", "in_review", "live", "rejected"]) {
      expect(statuses).toContain(s)
    }
  })

  it("orders newest first", async () => {
    const releases = await fetchReleases()
    const times = releases.map((r) => r.createdAt)
    expect(times).toEqual([...times].sort((a, b) => b.localeCompare(a)))
  })

  it("carries a live permalink and a rejection reason on the relevant rows", async () => {
    const releases = await fetchReleases()
    const live = releases.flatMap((r) => r.channels).find((c) => c.status === "live")
    const rejected = releases.flatMap((r) => r.channels).find((c) => c.status === "rejected")
    expect(live?.permalink).toMatch(/^https:\/\//)
    expect(rejected?.rejectionReason).toBeTruthy()
  })

  it("returns a defensive copy the caller can't use to mutate the seed", async () => {
    const first = await fetchReleases()
    first[0].channels[0].status = "draft"
    const second = await fetchReleases()
    expect(second.some((r) => r.channels.some((c) => c.status === "live"))).toBe(true)
  })
})
