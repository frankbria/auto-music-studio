import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ShareModal, shareUrlForClip } from "@/components/song/ShareModal"

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  })
  return writeText
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("shareUrlForClip", () => {
  it("builds an origin-rooted /song path and encodes the id", () => {
    expect(shareUrlForClip("c1")).toBe(`${window.location.origin}/song/c1`)
    expect(shareUrlForClip("a/b")).toBe(`${window.location.origin}/song/a%2Fb`)
  })
})

describe("ShareModal", () => {
  it("shows the copyable share link", () => {
    render(
      <ShareModal open clipId="c1" clipTitle="My Song" onClose={() => {}} />
    )
    const input = screen.getByLabelText<HTMLInputElement>("Share link")
    expect(input.value).toBe(shareUrlForClip("c1"))
    expect(input).toHaveAttribute("readonly")
  })

  it("copies the link and shows confirmation", async () => {
    // setup() installs its own clipboard stub, so ours must come after it.
    const user = userEvent.setup()
    const writeText = stubClipboard()
    render(
      <ShareModal open clipId="c1" clipTitle="My Song" onClose={() => {}} />
    )

    await user.click(screen.getByRole("button", { name: "Copy link" }))
    expect(writeText).toHaveBeenCalledWith(shareUrlForClip("c1"))
    await waitFor(() =>
      expect(screen.getByText("Copied!")).toBeInTheDocument()
    )
  })

  it("offers X and Facebook share intents pointed at the link", () => {
    render(
      <ShareModal open clipId="c1" clipTitle="My Song" onClose={() => {}} />
    )
    const encoded = encodeURIComponent(shareUrlForClip("c1"))

    const x = screen.getByRole("link", { name: /share on x/i })
    expect(x).toHaveAttribute("href", expect.stringContaining(encoded))
    expect(x).toHaveAttribute("target", "_blank")

    const fb = screen.getByRole("link", { name: /share on facebook/i })
    expect(fb).toHaveAttribute("href", expect.stringContaining(encoded))
  })

  it("calls onClose when dismissed", async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <ShareModal open clipId="c1" clipTitle="My Song" onClose={onClose} />
    )
    await user.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalled()
  })
})
