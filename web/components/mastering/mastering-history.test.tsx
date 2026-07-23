import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { MasteringHistory } from "@/components/mastering/mastering-history"
import type { MasteringHistoryEntry } from "@/lib/mastering-history"

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

function entry(over: Partial<MasteringHistoryEntry>): MasteringHistoryEntry {
  return {
    id: "mj",
    songTitle: "Song",
    profile: "streaming",
    service: "dolby",
    status: "completed",
    isApproved: false,
    createdAt: new Date().toISOString(),
    ...over,
  }
}

describe("MasteringHistory", () => {
  it("renders an empty state when there are no jobs", () => {
    render(<MasteringHistory entries={[]} />)
    expect(screen.getByText(/no mastering jobs yet/i)).toBeInTheDocument()
  })

  it("links an approved master to its song page (AC4)", () => {
    render(
      <MasteringHistory
        entries={[
          entry({ id: "a", songTitle: "Neon Skyline", isApproved: true, masteredClipId: "clip-neon" }),
        ]}
      />
    )
    const link = screen.getByRole("link", { name: /neon skyline/i })
    expect(link).toHaveAttribute("href", "/song/clip-neon")
    // Exact match — the card description also contains the word "approved".
    expect(screen.getByText("Approved")).toBeInTheDocument()
  })

  it("shows non-approved jobs without a link and with their status", () => {
    render(
      <MasteringHistory
        entries={[entry({ id: "p", songTitle: "Crownfall", status: "processing" })]}
      />
    )
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    expect(screen.getByText(/crownfall/i)).toBeInTheDocument()
    expect(screen.getByText(/processing/i)).toBeInTheDocument()
  })
})
