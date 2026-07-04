import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SongActionsMenu } from "@/components/song/SongActionsMenu"

function renderMenu(
  props: Partial<React.ComponentProps<typeof SongActionsMenu>> = {}
) {
  const onAction = vi.fn()
  render(
    <SongActionsMenu
      isPublic={false}
      isFreeTier={false}
      onAction={onAction}
      {...props}
    />
  )
  return { onAction }
}

async function openMenu() {
  await userEvent.click(
    screen.getByRole("button", { name: /song actions menu/i })
  )
  return screen.getByRole("menu")
}

describe("SongActionsMenu", () => {
  it("renders every operation grouped under its category header", async () => {
    renderMenu()
    await openMenu()

    for (const category of ["Edit", "Create", "Audio", "Export", "Manage"]) {
      expect(screen.getByText(category)).toBeInTheDocument()
    }
    for (const label of [
      "Remix",
      "Edit (Repaint)",
      "Open in Editor",
      "Open in Studio",
      "Cover",
      "Extend",
      "Mashup",
      "Sample from Song",
      "Use as Inspiration",
      "Add Vocal",
      "Remaster",
      "Replace Section",
      "Crop",
      "Adjust Speed",
      "Send to Mastering",
      "Export to DAW",
      "Create Music Video",
      "Download",
      "Publish",
      "Delete",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it("emits the action id when an item is selected", async () => {
    const { onAction } = renderMenu()
    await openMenu()

    await userEvent.click(screen.getByRole("menuitem", { name: /remaster/i }))
    expect(onAction).toHaveBeenCalledWith("remaster")
  })

  it("offers download formats in a submenu and emits their ids", async () => {
    const { onAction } = renderMenu()
    await openMenu()

    await userEvent.click(screen.getByRole("menuitem", { name: "Download" }))
    for (const label of ["MP3", "WAV", "FLAC", "Stems"]) {
      expect(screen.getByRole("menuitem", { name: new RegExp(label) })).toBeInTheDocument()
    }
    await userEvent.click(screen.getByRole("menuitem", { name: /WAV/ }))
    expect(onAction).toHaveBeenCalledWith("download-wav")
  })

  it("labels the publish item from the current visibility", async () => {
    renderMenu({ isPublic: true })
    await openMenu()
    expect(screen.getByText("Unpublish")).toBeInTheDocument()
    expect(screen.queryByText(/^Publish$/)).not.toBeInTheDocument()
  })

  it("locks Pro-only actions for free-tier users", async () => {
    const { onAction } = renderMenu({ isFreeTier: true })
    await openMenu()

    const editor = screen.getByRole("menuitem", { name: /open in editor/i })
    expect(editor).toHaveAttribute("aria-disabled", "true")
    // Pro badge is visible on gated items.
    expect(screen.getAllByText("Pro").length).toBeGreaterThanOrEqual(4)

    await userEvent.click(editor)
    expect(onAction).not.toHaveBeenCalled()
  })

  it("keeps Pro badges but no lock for pro users", async () => {
    renderMenu({ isFreeTier: false })
    await openMenu()

    const editor = screen.getByRole("menuitem", { name: /open in editor/i })
    expect(editor).not.toHaveAttribute("aria-disabled", "true")
    expect(screen.getAllByText("Pro").length).toBeGreaterThanOrEqual(4)
  })

  it("supports keyboard navigation: arrows move focus, Escape closes", async () => {
    renderMenu()
    const trigger = screen.getByRole("button", { name: /song actions menu/i })
    trigger.focus()
    await userEvent.keyboard("{Enter}")
    expect(screen.getByRole("menu")).toBeInTheDocument()

    // Keyboard open focuses the first item; ArrowDown moves to the next.
    expect(screen.getByRole("menuitem", { name: "Remix" })).toHaveFocus()
    await userEvent.keyboard("{ArrowDown}")
    expect(
      screen.getByRole("menuitem", { name: "Edit (Repaint)" })
    ).toHaveFocus()

    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
  })
})
