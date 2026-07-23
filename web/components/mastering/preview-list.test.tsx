import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PreviewList } from "@/components/mastering/preview-list"
import type { PreviewItem } from "@/lib/mastering"

const items: PreviewItem[] = [
  { preview_id: "m1", audio_url: "u1", profile: "streaming", service: "dolby", loudness_delta: 6 },
  { preview_id: "m2", audio_url: "u2", profile: "club", service: "landr", loudness_delta: -2 },
]

afterEach(() => vi.clearAllMocks())

describe("PreviewList", () => {
  it("renders an empty state with no previews", () => {
    render(<PreviewList previews={[]} selectedId={null} onSelect={vi.fn()} />)
    expect(screen.getByText(/no mastered previews/i)).toBeInTheDocument()
  })

  it("renders each preview with profile, service, and signed loudness delta", () => {
    render(<PreviewList previews={items} selectedId="m1" onSelect={vi.fn()} />)
    expect(screen.getByText("Streaming")).toBeInTheDocument()
    expect(screen.getByText("Dolby.io")).toBeInTheDocument()
    expect(screen.getByText("+6.0 dB")).toBeInTheDocument()
    expect(screen.getByText("-2.0 dB")).toBeInTheDocument()
  })

  it("marks the selected preview as pressed and reports clicks", async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<PreviewList previews={items} selectedId="m1" onSelect={onSelect} />)

    const buttons = screen.getAllByRole("button")
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true")
    expect(buttons[1]).toHaveAttribute("aria-pressed", "false")

    await user.click(buttons[1])
    expect(onSelect).toHaveBeenCalledWith("m2")
  })
})
