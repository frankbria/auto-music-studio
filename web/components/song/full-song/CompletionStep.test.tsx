import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CompletionStep } from "@/components/song/full-song/CompletionStep"
import { PlayerProvider } from "@/contexts/player-context"

function renderCompletion(
  props: Partial<React.ComponentProps<typeof CompletionStep>> = {}
) {
  const handlers = { onOpenSongDetail: vi.fn(), onClose: vi.fn() }
  render(
    <PlayerProvider>
      <CompletionStep
        finalClipId="final-1"
        seedTitle="Midnight"
        totalDuration={210}
        sectionsCompleted={7}
        creditsUsed={8}
        {...handlers}
        {...props}
      />
    </PlayerProvider>
  )
  return handlers
}

describe("CompletionStep", () => {
  it("confirms the song is saved and summarizes the build", () => {
    renderCompletion()
    expect(screen.getByText(/saved to your workspace/i)).toBeInTheDocument()
    // 3:30 shows in both the preview player and the summary row.
    expect(screen.getAllByText("3:30").length).toBeGreaterThan(0)
    expect(screen.getByText("7")).toBeInTheDocument() // sections
    expect(screen.getByText("8")).toBeInTheDocument() // credits
  })

  it("wires the open-in-song-detail and close buttons", async () => {
    const { onOpenSongDetail, onClose } = renderCompletion()
    await userEvent.click(
      screen.getByRole("button", { name: /open in song detail/i })
    )
    expect(onOpenSongDetail).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
