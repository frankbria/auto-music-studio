import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SectionReviewStep } from "@/components/song/full-song/SectionReviewStep"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import type { Section } from "@/lib/song-structure"

const section: Section = {
  name: "chorus",
  durationSeconds: 31,
  styleHint: "chorus, hook, energetic, full arrangement",
}

function NowPlayingArtist() {
  return <p data-testid="now-playing">{usePlayer().state.current?.artist}</p>
}

function renderReview(
  props: Partial<React.ComponentProps<typeof SectionReviewStep>> = {}
) {
  const handlers = {
    onAccept: vi.fn(),
    onReject: vi.fn(),
    onRegenerate: vi.fn(),
  }
  render(
    <PlayerProvider>
      <SectionReviewStep
        section={section}
        sectionNumber={3}
        totalSections={7}
        clipId="gen-3"
        seedTitle="Midnight"
        rejected={false}
        regenAttempts={0}
        {...handlers}
        {...props}
      />
      <NowPlayingArtist />
    </PlayerProvider>
  )
  return handlers
}

describe("SectionReviewStep", () => {
  it("plays the section under the seed clip's artist (#735)", async () => {
    renderReview({ seedArtist: "Ivory Lanes" })
    await userEvent.click(screen.getByRole("button", { name: /play preview/i }))
    expect(screen.getByTestId("now-playing")).toHaveTextContent("Ivory Lanes")
  })

  it("previews the section and offers accept / reject", () => {
    renderReview()
    expect(screen.getByText(/Section 3 of 7/)).toBeInTheDocument()
    expect(screen.getByText("Midnight — chorus")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /play preview/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument()
  })

  it("accepts the section", async () => {
    const { onAccept } = renderReview()
    await userEvent.click(screen.getByRole("button", { name: "Accept" }))
    expect(onAccept).toHaveBeenCalledOnce()
  })

  it("reveals the regeneration field once rejected and regenerates with instructions", async () => {
    const { onRegenerate } = renderReview({ rejected: true, regenAttempts: 1 })
    expect(screen.getByText(/Regenerated 1 time/)).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(/what should change/i),
      "add a guitar lead"
    )
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))
    expect(onRegenerate).toHaveBeenCalledWith("add a guitar lead")
  })
})
