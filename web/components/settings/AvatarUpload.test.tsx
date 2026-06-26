import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AvatarUpload } from "@/components/settings/AvatarUpload"

beforeEach(() => {
  // jsdom has no object-URL support.
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:preview"),
    revokeObjectURL: vi.fn(),
  })
})
afterEach(() => vi.restoreAllMocks())

describe("AvatarUpload", () => {
  it("shows the 'coming soon' note (upload not yet persisted)", () => {
    render(<AvatarUpload currentUrl={null} />)
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument()
  })

  it("previews the image after a valid file is chosen", async () => {
    render(<AvatarUpload currentUrl={null} />)
    const user = userEvent.setup()
    const file = new File(["x"], "a.png", { type: "image/png" })
    await user.upload(screen.getByLabelText("Avatar image"), file)

    const img = screen.getByAltText("Avatar preview") as HTMLImageElement
    expect(img.src).toContain("blob:preview")
  })

  it("rejects a non-image file dropped onto the zone", () => {
    // Drag-and-drop bypasses the input's `accept` filter, so the component must
    // validate the type itself — exercise that path directly.
    render(<AvatarUpload currentUrl={null} />)
    const file = new File(["x"], "a.txt", { type: "text/plain" })
    const zone = screen.getByText(/Drag an image here/)
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })

    expect(screen.getByRole("alert")).toHaveTextContent(/image/i)
    expect(screen.queryByAltText("Avatar preview")).not.toBeInTheDocument()
  })
})
