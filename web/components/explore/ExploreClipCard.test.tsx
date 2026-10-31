import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ExploreClipCard } from "@/components/explore/ExploreClipCard"
import { makeClip } from "@/test/clip-factory"
import { SignedIn } from "@/test/signed-in"

describe("ExploreClipCard", () => {
  it("links the whole card to the song detail page (AC5)", () => {
    render(<ExploreClipCard clip={makeClip({ id: "abc", title: "Neon" })} />)
    const link = screen.getByRole("link", { name: /neon/i })
    expect(link).toHaveAttribute("href", "/song/abc")
  })

  it("renders engagement stats only when present", () => {
    render(
      <ExploreClipCard
        clip={makeClip({ play_count: 8200, like_count: 640, share_count: 210 })}
      />
    )
    // Intl compact: 8200 → "8.2K".
    expect(screen.getByText("8.2K")).toBeInTheDocument()
  })

  it("renders no stats for a public clip without counters", () => {
    render(<ExploreClipCard clip={makeClip({ duration: null, model: null })} />)
    expect(screen.getByTestId("explore-clip-card")).not.toHaveTextContent(/\d/)
  })

  it("has a Report button outside the card link (US-27.2)", () => {
    render(
      <SignedIn>
        <ExploreClipCard clip={makeClip({ id: "abc", title: "Neon" })} />
      </SignedIn>
    )
    const report = screen.getByRole("button", { name: "Report" })
    expect(report.closest("a")).toBeNull()
  })
})
