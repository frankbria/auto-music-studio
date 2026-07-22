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

describe("PlaylistLibrary", () => {
  it("lists the seeded playlists", () => {
    renderLibrary()
    expect(screen.getByText("Late Night Drive")).toBeInTheDocument()
    expect(screen.getByText("Deep Focus")).toBeInTheDocument()
    expect(screen.getByText("Summer Anthems")).toBeInTheDocument()
  })

  it("creates a playlist (AC1)", async () => {
    const user = userEvent.setup()
    renderLibrary()
    await user.click(screen.getByRole("button", { name: "New playlist" }))
    await user.type(screen.getByLabelText("Name"), "Roadtrip")
    await user.click(screen.getByRole("button", { name: "Create" }))
    expect(screen.getByText("Roadtrip")).toBeInTheDocument()
  })

  it("renames a playlist (AC1)", async () => {
    const user = userEvent.setup()
    renderLibrary()
    const card = cardFor("Deep Focus")
    await user.click(within(card).getByRole("button", { name: "Actions for Deep Focus" }))
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
    const card = cardFor("Summer Anthems")
    await user.click(within(card).getByRole("button", { name: "Actions for Summer Anthems" }))
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }))
    // Confirmation dialog, then the actual delete.
    await user.click(screen.getByRole("button", { name: "Delete" }))
    expect(screen.queryByText("Summer Anthems")).not.toBeInTheDocument()
  })
})
