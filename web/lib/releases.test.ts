import { afterEach, describe, expect, it, vi } from "vitest"

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
    expect(
      externalLink({
        channel: "soundcloud",
        status: "submitted",
        permalink: "https://x",
      })
    ).toBeNull()
  })

  it("rejects non-http(s) schemes (XSS guard) and malformed URLs", () => {
    expect(
      externalLink({ ...base, permalink: "javascript:alert(document.cookie)" })
    ).toBeNull()
    expect(
      externalLink({ ...base, permalink: "data:text/html,<script>x</script>" })
    ).toBeNull()
    expect(externalLink({ ...base, permalink: "not a url" })).toBeNull()
    expect(externalLink({ ...base, permalink: "http://ok" })).toBe("http://ok")
  })
})

describe("fetchReleases", () => {
  afterEach(() => vi.unstubAllGlobals())

  const apiRelease = {
    id: "r1",
    clip_id: "c1",
    title: "Neon Rain",
    artist: "Juno Vale",
    genre: "Synthwave",
    release_date: "2026-11-01T00:00:00Z",
    album_name: null,
    isrc: "US-AMS-26-00001",
    upc: null,
    created_at: "2026-11-02T10:00:00Z",
    channel_statuses: { soundcloud: "live", landr: "rejected" },
    channel_permalinks: { soundcloud: "https://soundcloud.com/juno/neon-rain" },
    channel_rejection_reasons: { landr: "Artwork too small." },
  }

  it("reads the caller's releases through the BFF with their token, mapped for the dashboard", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ releases: [apiRelease], total: 1 }), {
          status: 200,
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const releases = await fetchReleases("tok")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/releases")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(releases).toEqual([
      {
        id: "r1",
        clipId: "c1",
        title: "Neon Rain",
        artist: "Juno Vale",
        genre: "Synthwave",
        releaseDate: "2026-11-01T00:00:00Z",
        album: null,
        isrc: "US-AMS-26-00001",
        upc: null,
        createdAt: "2026-11-02T10:00:00Z",
        channels: [
          {
            channel: "soundcloud",
            status: "live",
            permalink: "https://soundcloud.com/juno/neon-rain",
            rejectionReason: null,
          },
          {
            channel: "landr",
            status: "rejected",
            permalink: null,
            rejectionReason: "Artwork too small.",
          },
        ],
      },
    ])
  })

  it("orders newest first", async () => {
    const older = {
      ...apiRelease,
      id: "old",
      created_at: "2026-10-01T00:00:00Z",
    }
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ releases: [older, apiRelease], total: 2 }),
            { status: 200 }
          )
        )
    )
    expect((await fetchReleases("tok")).map((r) => r.id)).toEqual(["r1", "old"])
  })

  it("returns an empty list when the user has no releases", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ releases: [], total: 0 }), {
            status: 200,
          })
        )
    )
    expect(await fetchReleases("tok")).toEqual([])
  })

  it("throws on a failed response so the dashboard shows its error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 502 }))
    )
    await expect(fetchReleases("tok")).rejects.toThrow()
  })
})
