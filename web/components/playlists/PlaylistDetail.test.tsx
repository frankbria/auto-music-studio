import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { PlaylistDetail } from "@/components/playlists/PlaylistDetail"
import { PlaylistsProvider, usePlaylists } from "@/contexts/playlists-context"
import { makeClip } from "@/test/clip-factory"
import { discoverPage, stubDiscoverFetch } from "@/test/discover-api"

const SONGS = [
  makeClip({ id: "neon", title: "Neon Skyline", is_public: true }),
  makeClip({ id: "velvet", title: "Velvet Static", is_public: true }),
  makeClip({ id: "pulse", title: "Pulse Theory", is_public: true }),
]

// The store starts empty, so create the playlist the way a user would, then
// show its detail page.
function CreatedPlaylist() {
  const { playlists, create } = usePlaylists()
  const pl = playlists[0]
  if (!pl) {
    return <button onClick={() => create("Late Night Drive")}>Seed</button>
  }
  return <PlaylistDetail playlistId={pl.id} />
}

async function renderDetail({ songs = SONGS } = {}) {
  const user = userEvent.setup()
  render(
    <PlaylistsProvider>
      <CreatedPlaylist />
    </PlaylistsProvider>
  )
  await user.click(screen.getByRole("button", { name: "Seed" }))
  if (songs.length > 0) {
    await user.click(screen.getAllByRole("button", { name: "Add songs" })[0])
    for (const song of songs) {
      await user.click(
        await screen.findByRole("button", { name: `Add ${song.title}` })
      )
    }
    await user.keyboard("{Escape}")
  }
  return user
}

const rows = () => screen.getAllByTestId("playlist-song-row")
// Each row has two links: [0] the play affordance, [1] the title. Use the title.
const firstRowTitle = () =>
  within(rows()[0]).getAllByRole("link")[1].textContent

beforeEach(() => {
  stubDiscoverFetch(() => discoverPage(SONGS))
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("PlaylistDetail", () => {
  it("shows a not-found state for an unknown playlist", () => {
    render(
      <PlaylistsProvider>
        <PlaylistDetail playlistId="nope" />
      </PlaylistsProvider>
    )
    expect(screen.getByText("Playlist not found")).toBeInTheDocument()
  })

  it("starts a new playlist empty", async () => {
    await renderDetail({ songs: [] })
    expect(screen.getByTestId("playlist-songs-empty")).toBeInTheDocument()
  })

  it("lists the songs added from discovery, with playback links (AC2)", async () => {
    await renderDetail()
    expect(rows()).toHaveLength(3)
    expect(firstRowTitle()).toBe("Neon Skyline")
    expect(within(rows()[0]).getAllByRole("link")[0]).toHaveAttribute(
      "href",
      "/song/neon"
    )
  })

  it("reorders songs down with the move button (AC2)", async () => {
    const user = await renderDetail()
    await user.click(
      within(rows()[0]).getByRole("button", { name: "Move down" })
    )
    expect(firstRowTitle()).toBe("Velvet Static")
  })

  it("removes a song (AC2)", async () => {
    const user = await renderDetail()
    await user.click(
      within(rows()[0]).getByRole("button", {
        name: /Remove .* from playlist/,
      })
    )
    expect(rows()).toHaveLength(2)
    expect(screen.queryByText("Neon Skyline")).not.toBeInTheDocument()
  })

  it("shows a share link once public and hides it when private (AC3, AC6)", async () => {
    const user = await renderDetail({ songs: [] })
    const shareText = /\/playlists\/pl-/
    expect(screen.queryByText(shareText)).not.toBeInTheDocument()

    await user.click(screen.getByRole("switch", { name: /Public playlist/i }))
    expect(screen.getByText(shareText)).toBeInTheDocument()

    await user.click(screen.getByRole("switch", { name: /Public playlist/i }))
    expect(screen.queryByText(shareText)).not.toBeInTheDocument()
    expect(
      screen.getByText(/Make this playlist public to get a shareable link/)
    ).toBeInTheDocument()
  })

  it("links Use as Inspiration to the create page with playlist context (AC5)", async () => {
    await renderDetail({ songs: [] })
    const link = screen.getByRole("link", { name: /Use as Inspiration/ })
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/create?inspiration=pl-")
    )
  })
})
