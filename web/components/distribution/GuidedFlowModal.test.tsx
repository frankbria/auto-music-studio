import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { GuidedFlowModal } from "@/components/distribution/GuidedFlowModal"
import type { ReleaseMetadata } from "@/lib/release-draft"

function metadata(overrides: Partial<ReleaseMetadata> = {}): ReleaseMetadata {
  return {
    title: "Nightfall",
    artist: "AMS",
    album: "",
    genre: "House",
    description: "",
    bpm: 124,
    key: "Am",
    language: "",
    explicit: false,
    releaseDate: "",
    copyright: "",
    credits: { producer: "", songwriter: "", performer: "" },
    coverArt: { kind: "existing" },
    isrc: "US-AMS-25-00001",
    upc: "012345678905",
    lyrics: "",
    ...overrides,
  }
}

beforeEach(() => {
  vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:pkg", revokeObjectURL: vi.fn() })
})
afterEach(() => vi.unstubAllGlobals())

describe("GuidedFlowModal", () => {
  it("disables Prepare when no song is selected", () => {
    render(<GuidedFlowModal target="landr" ready={false} resolveMetadata={() => null} />)
    expect(screen.getByRole("button", { name: /prepare package/i })).toBeDisabled()
  })

  it("resolves the metadata fresh when the modal opens", async () => {
    const resolveMetadata = vi.fn(() => metadata())
    render(<GuidedFlowModal target="landr" ready resolveMetadata={resolveMetadata} />)
    expect(resolveMetadata).not.toHaveBeenCalled() // not read until opened
    await userEvent.click(screen.getByRole("button", { name: /prepare package/i }))
    await screen.findByRole("dialog")
    expect(resolveMetadata).toHaveBeenCalledTimes(1)
  })

  it("shows an open-in-new-tab link to LANDR when every check passes", async () => {
    render(<GuidedFlowModal target="landr" ready resolveMetadata={() => metadata()} />)
    await userEvent.click(screen.getByRole("button", { name: /prepare package/i }))

    const dialog = await screen.findByRole("dialog")
    const openLink = within(dialog).getByRole("link", { name: /open landr/i })
    expect(openLink).toHaveAttribute("href", expect.stringMatching(/landr\.com/))
    expect(openLink).toHaveAttribute("target", "_blank")
    // The bundle is downloadable.
    expect(within(dialog).getByRole("link", { name: /download package/i })).toHaveAttribute(
      "download"
    )
  })

  it("withholds the bundle and lists failed checks for incomplete metadata", async () => {
    render(
      <GuidedFlowModal
        target="distrokid"
        ready
        resolveMetadata={() => metadata({ coverArt: { kind: "none" } })}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: /prepare package/i }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).queryByRole("link", { name: /download package/i })).toBeNull()
    expect(within(dialog).getByText("Cover art")).toBeInTheDocument()
  })
})
