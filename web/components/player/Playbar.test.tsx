import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

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
