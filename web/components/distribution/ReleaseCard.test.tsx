import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ReleaseCard } from "@/components/distribution/ReleaseCard"
import type { ReleaseSummary } from "@/lib/releases"

function make(overrides: Partial<ReleaseSummary> = {}): ReleaseSummary {
  return {
    id: "rel-1",
    clipId: "clip-1",
    title: "Neon Skyline",
    artist: "Ivory Lanes",
    genre: "Synthwave",
    releaseDate: "2026-06-01",
    isrc: "US-AMS-26-00012",
    upc: "0885686000121",
    createdAt: new Date().toISOString(),
    channels: [{ channel: "soundcloud", status: "live", permalink: "https://sc/x" }],
    ...overrides,
  }
}

describe("ReleaseCard", () => {
  it("shows title, artist, and identifiers", () => {
    render(<ReleaseCard release={make()} />)
    expect(screen.getByRole("link", { name: "Neon Skyline" })).toHaveAttribute("href", "/song/clip-1")
    expect(screen.getByText(/Ivory Lanes/)).toBeInTheDocument()
    expect(screen.getByText(/ISRC US-AMS-26-00012/)).toBeInTheDocument()
    expect(screen.getByText(/UPC 0885686000121/)).toBeInTheDocument()
  })

  it("links live channels to the external platform in a new tab", () => {
    render(<ReleaseCard release={make()} />)
    const link = screen.getByRole("link", { name: /View on SoundCloud/i })
    expect(link).toHaveAttribute("href", "https://sc/x")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"))
  })

  it("shows the rejection reason for a rejected channel", () => {
    render(
      <ReleaseCard
        release={make({ channels: [{ channel: "distrokid", status: "rejected", rejectionReason: "Bad art." }] })}
      />
    )
    expect(screen.getByText("Bad art.")).toBeInTheDocument()
  })

  it("falls back to 'Reason unavailable' when a rejected channel has no reason", () => {
    render(
      <ReleaseCard release={make({ channels: [{ channel: "distrokid", status: "rejected" }] })} />
    )
    expect(screen.getByText(/Reason unavailable/i)).toBeInTheDocument()
  })

  it("shows no external link for non-live channels", () => {
    render(<ReleaseCard release={make({ channels: [{ channel: "landr", status: "submitted" }] })} />)
    expect(screen.queryByRole("link", { name: /View on/i })).not.toBeInTheDocument()
  })
})
