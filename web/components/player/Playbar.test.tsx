import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { Playbar } from "@/components/player/Playbar"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"

function QueueLength() {
  const { state } = usePlayer()
  return <span data-testid="queue-length">{state.queue.length}</span>
}

describe("Playbar (#654)", () => {
  it("starts empty instead of seeding demo tracks", () => {
    render(
      <PlayerProvider>
        <Playbar />
        <QueueLength />
      </PlayerProvider>
    )
    expect(screen.getByText("Nothing playing")).toBeInTheDocument()
    expect(screen.getByTestId("queue-length")).toHaveTextContent("0")
  })
})

function LoadTrack() {
  const { dispatch } = usePlayer()
  return (
    <button
      onClick={() => {
        dispatch({
          type: "play/track",
          track: {
            id: "t1",
            title: "Night Drive",
            artist: "A",
            audioUrl: "/a.wav",
          },
        })
        dispatch({ type: "duration/set", duration: 200 })
        dispatch({ type: "time/set", time: 65 })
      }}
    >
      load
    </button>
  )
}

describe("Playbar keyboard and screen reader use (#340)", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue()
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {})
  })
  afterEach(() => vi.restoreAllMocks())

  it("puts every control in the tab order, and the sliders read as time and percent", async () => {
    const user = userEvent.setup()
    render(
      <PlayerProvider>
        <LoadTrack />
        <Playbar />
      </PlayerProvider>
    )
    await user.click(screen.getByText("load"))

    const seek = screen.getByRole("slider", { name: "Seek" })
    expect(seek).toHaveAttribute("aria-valuetext", "1:05 of 3:20")
    expect(screen.getByRole("slider", { name: "Volume" })).toHaveAttribute(
      "aria-valuetext",
      expect.stringMatching(/^\d+%$/)
    )

    const reached = new Set<Element>()
    for (let i = 0; i < 30; i++) {
      await user.tab()
      if (document.activeElement) reached.add(document.activeElement)
    }
    for (const control of [
      seek,
      screen.getByRole("slider", { name: "Volume" }),
      ...screen
        .getAllByRole("button")
        .filter((b) => !b.hasAttribute("disabled")),
    ]) {
      expect(
        reached.has(control),
        control.getAttribute("aria-label") ?? ""
      ).toBe(true)
    }
  })
})
