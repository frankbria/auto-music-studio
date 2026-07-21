import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { PlaylistDetail } from "@/components/playlists/PlaylistDetail"
import { PlaylistsProvider } from "@/contexts/playlists-context"

// pl-latenight is seeded public with 5 songs: Neon Skyline, Velvet Static,
// Pulse Theory, Paper Lanterns, Monochrome Heart (in that order).
function renderDetail(id = "pl-latenight") {
  return render(
    <PlaylistsProvider>
      <PlaylistDetail playlistId={id} />
    </PlaylistsProvider>
  )
}

const rows = () => screen.getAllByTestId("playlist-song-row")
// Each row has two links: [0] the play affordance, [1] the title. Use the title.
const firstRowTitle = () => within(rows()[0]).getAllByRole("link")[1].textContent

describe("PlaylistDetail", () => {
  it("shows a not-found state for an unknown playlist", () => {
    renderDetail("nope")
    expect(screen.getByText("Playlist not found")).toBeInTheDocument()
  })

  it("lists the playlist songs with playback links", () => {
    renderDetail()
    expect(rows()).toHaveLength(5)
    expect(within(rows()[0]).getAllByRole("link")[0]).toHaveAttribute(
      "href",
      "/song/clip-neon"
    )
  })

  it("reorders songs down with the move button (AC2)", async () => {
    const user = userEvent.setup()
    renderDetail()
    expect(firstRowTitle()).toBe("Neon Skyline")
    await user.click(within(rows()[0]).getByRole("button", { name: "Move down" }))
    expect(firstRowTitle()).toBe("Velvet Static")
  })

  it("removes a song (AC2)", async () => {
    const user = userEvent.setup()
    renderDetail()
    await user.click(
      within(rows()[0]).getByRole("button", { name: /Remove .* from playlist/ })
    )
    expect(rows()).toHaveLength(4)
    expect(screen.queryByText("Neon Skyline")).not.toBeInTheDocument()
  })

  it("opens the add-songs dialog (AC2)", async () => {
    const user = userEvent.setup()
    renderDetail()
    await user.click(screen.getAllByRole("button", { name: "Add songs" })[0])
    expect(await screen.findByRole("dialog")).toHaveTextContent("Add songs")
  })

  it("shows a share link for a public playlist and hides it when private (AC3, AC6)", async () => {
    const user = userEvent.setup()
    renderDetail()
    expect(screen.getByText(/\/playlists\/pl-latenight/)).toBeInTheDocument()

    await user.click(screen.getByRole("switch", { name: /Public playlist/i }))
    expect(screen.queryByText(/\/playlists\/pl-latenight/)).not.toBeInTheDocument()
    expect(
      screen.getByText(/Make this playlist public to get a shareable link/)
    ).toBeInTheDocument()
  })

  it("links Use as Inspiration to the create page with playlist context (AC5)", () => {
    renderDetail()
    const link = screen.getByRole("link", { name: /Use as Inspiration/ })
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/create?inspiration=pl-latenight")
    )
  })
})
