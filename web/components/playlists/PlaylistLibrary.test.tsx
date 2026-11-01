import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { PlaylistLibrary } from "@/components/playlists/PlaylistLibrary"
import { PlaylistsProvider } from "@/contexts/playlists-context"

function renderLibrary() {
  return render(
    <PlaylistsProvider>
      <PlaylistLibrary />
    </PlaylistsProvider>
  )
}

const cardFor = (name: string) =>
  screen.getByText(name).closest("[class*='group/card']") as HTMLElement

async function createPlaylist(
  user: ReturnType<typeof userEvent.setup>,
  name: string
) {
  await user.click(screen.getAllByRole("button", { name: "New playlist" })[0])
  await user.type(screen.getByLabelText("Name"), name)
  await user.click(screen.getByRole("button", { name: "Create" }))
}

describe("PlaylistLibrary", () => {
  it("starts with no playlists", () => {
    renderLibrary()
    expect(screen.getByTestId("playlists-empty")).toBeInTheDocument()
  })

  it("creates a playlist (AC1)", async () => {
    const user = userEvent.setup()
    renderLibrary()
    await createPlaylist(user, "Roadtrip")
    expect(screen.getByText("Roadtrip")).toBeInTheDocument()
  })

  it("renames a playlist (AC1)", async () => {
    const user = userEvent.setup()
    renderLibrary()
    await createPlaylist(user, "Deep Focus")
    const card = cardFor("Deep Focus")
    await user.click(
      within(card).getByRole("button", { name: "Actions for Deep Focus" })
    )
    await user.click(await screen.findByRole("menuitem", { name: /Rename/ }))
    const input = screen.getByLabelText("Name")
    await user.clear(input)
    await user.type(input, "Focus Flow")
    await user.click(screen.getByRole("button", { name: "Save" }))
    expect(screen.getByText("Focus Flow")).toBeInTheDocument()
    expect(screen.queryByText("Deep Focus")).not.toBeInTheDocument()
  })

  it("deletes a playlist with confirmation (AC1)", async () => {
    const user = userEvent.setup()
    renderLibrary()
    await createPlaylist(user, "Summer Anthems")
    const card = cardFor("Summer Anthems")
    await user.click(
      within(card).getByRole("button", { name: "Actions for Summer Anthems" })
    )
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }))
    // Confirmation dialog, then the actual delete.
    await user.click(screen.getByRole("button", { name: "Delete" }))
    expect(screen.queryByText("Summer Anthems")).not.toBeInTheDocument()
  })
})
