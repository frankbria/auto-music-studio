import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { SongActionModal } from "@/components/song/SongActionModal"
import { makeClip } from "@/test/clip-factory"

// Each editing modal is exercised in its own test; here we only verify the
// dispatch maps an action id to the right modal (or the placeholder), so the
// modals are stubbed to lightweight markers.
vi.mock("@/components/song/modals/CropModal", () => ({
  CropModal: () => <div data-testid="crop-modal" />,
}))
vi.mock("@/components/song/modals/SpeedModal", () => ({
  SpeedModal: () => <div data-testid="speed-modal" />,
}))
vi.mock("@/components/song/modals/ExtendModal", () => ({
  ExtendModal: () => <div data-testid="extend-modal" />,
}))
vi.mock("@/components/song/modals/CoverModal", () => ({
  CoverModal: () => <div data-testid="cover-modal" />,
}))
vi.mock("@/components/song/modals/RemixModal", () => ({
  RemixModal: () => <div data-testid="remix-modal" />,
}))
vi.mock("@/components/song/modals/ReplaceSectionModal", () => ({
  ReplaceSectionModal: () => <div data-testid="replace-modal" />,
}))
vi.mock("@/components/song/modals/SampleModal", () => ({
  SampleModal: () => <div data-testid="sample-modal" />,
}))
vi.mock("@/components/song/modals/AddVocalModal", () => ({
  AddVocalModal: () => <div data-testid="add-vocal-modal" />,
}))
vi.mock("@/components/song/modals/MashupModal", () => ({
  MashupModal: () => <div data-testid="mashup-modal" />,
}))

const clip = makeClip()

describe("SongActionModal dispatch", () => {
  it("renders nothing when no action is active", () => {
    const { container } = render(
      <SongActionModal clip={clip} action={null} onClose={vi.fn()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it.each([
    ["crop", "crop-modal"],
    ["adjust-speed", "speed-modal"],
    ["extend", "extend-modal"],
    ["cover", "cover-modal"],
    ["remix", "remix-modal"],
    ["replace-section", "replace-modal"],
    ["repaint", "replace-modal"],
    ["sample", "sample-modal"],
    ["add-vocal", "add-vocal-modal"],
    ["mashup", "mashup-modal"],
  ] as const)("routes %s to its modal", (action, testId) => {
    render(<SongActionModal clip={clip} action={action} onClose={vi.fn()} />)
    expect(screen.getByTestId(testId)).toBeInTheDocument()
  })

  it("shows the not-available placeholder for a not-yet-built modal action", () => {
    render(<SongActionModal clip={clip} action="export-daw" onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent(/isn't available yet/i)
  })
})
