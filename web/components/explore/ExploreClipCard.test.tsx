import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ExploreClipCard } from "@/components/explore/ExploreClipCard"
import { makeClip } from "@/test/clip-factory"

describe("ExploreClipCard", () => {
  it("links the whole card to the song detail page (AC5)", () => {
    render(<ExploreClipCard clip={makeClip({ id: "abc", title: "Neon" })} />)
    const link = screen.getByRole("link", { name: /neon/i })
    expect(link).toHaveAttribute("href", "/song/abc")
  })

  it("shows a ranking number only when rank is provided (AC4)", () => {
    const { rerender } = render(
      <ExploreClipCard clip={makeClip()} rank={3} />
    )
    expect(screen.getByTestId("clip-rank")).toHaveTextContent("3")

    rerender(<ExploreClipCard clip={makeClip()} />)
    expect(screen.queryByTestId("clip-rank")).not.toBeInTheDocument()
  })

  it("renders engagement stats when present", () => {
    render(
      <ExploreClipCard
        clip={makeClip({ play_count: 8200, like_count: 640, share_count: 210 })}
      />
    )
    // Intl compact: 8200 → "8.2K".
    expect(screen.getByText("8.2K")).toBeInTheDocument()
  })
})
