import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AddInspirationModal } from "@/components/create/modals/AddInspirationModal"
import { MOCK_PLAYLISTS } from "@/lib/audio-inputs"

afterEach(() => vi.clearAllMocks())

describe("AddInspirationModal", () => {
  it("lists the user's playlists", () => {
    render(
      <AddInspirationModal open onOpenChange={() => {}} onSelect={() => {}} />
    )
    for (const playlist of MOCK_PLAYLISTS) {
      expect(screen.getByText(playlist.name)).toBeInTheDocument()
    }
  })

  it("selects a playlist and closes", async () => {
    const onSelect = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    render(
      <AddInspirationModal
        open
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />
    )

    await user.click(
      screen.getByRole("button", { name: /late night drive/i })
    )
    expect(onSelect).toHaveBeenCalledWith({
      id: "pl-latenight",
      name: "Late Night Drive",
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
