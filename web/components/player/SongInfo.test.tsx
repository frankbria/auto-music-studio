import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { SongInfo } from "@/components/player/SongInfo"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import type { Track } from "@/lib/clips"

function Load({ track }: { track: Track }) {
  const { dispatch } = usePlayer()
  return (
    <button onClick={() => dispatch({ type: "play/track", track })}>
      load {track.id}
    </button>
  )
}

const track = (id: string): Track => ({
  id,
  title: `Song ${id}`,
  artist: "A",
  audioUrl: `/api/clips/${id}/stream`,
  artworkUrl: `/api/clips/${id}/artwork`,
})

function renderInfo() {
  const { container } = render(
    <PlayerProvider>
      <SongInfo />
      <Load track={track("t1")} />
      <Load track={track("t2")} />
    </PlayerProvider>
  )
  return container
}

describe("SongInfo artwork (#737)", () => {
  it("shows the clip's cover art", async () => {
    const container = renderInfo()
    await userEvent.click(screen.getByText("load t1"))
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/clips/t1/artwork"
    )
  })

  it("falls back to the music-note glyph when the art fails to load, and retries for the next track", async () => {
    const container = renderInfo()
    await userEvent.click(screen.getByText("load t1"))
    fireEvent.error(container.querySelector("img")!)

    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("svg")).not.toBeNull()

    await userEvent.click(screen.getByText("load t2"))
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/clips/t2/artwork"
    )
  })
})
