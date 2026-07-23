import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { DistributionForm } from "@/components/release/DistributionForm"
import { loadDraft } from "@/lib/release-draft"
import type { Clip } from "@/lib/workspace-clips"

function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip-1",
    workspace_id: "ws-1",
    title: "Midnight Drive",
    format: "wav",
    duration: 180,
    bpm: 122,
    key: "A minor",
    style_tags: ["synthwave"],
    lyrics: "neon lights",
    vocal_language: "en",
    model: "ace-step",
    seed: 42,
    inference_steps: 30,
    parent_clip_ids: [],
    generation_mode: "text",
    is_public: false,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  }
}

beforeEach(() => localStorage.clear())
afterEach(() => localStorage.clear())

describe("DistributionForm", () => {
  it("prompts to select a song when no clip is chosen", () => {
    render(<DistributionForm clip={null} />)
    expect(screen.getByText(/select a song/i)).toBeInTheDocument()
  })

  it("pre-populates fields from the selected song (AC1)", () => {
    render(<DistributionForm clip={makeClip()} />)
    expect(screen.getByLabelText(/^title/i)).toHaveValue("Midnight Drive")
    expect(screen.getByLabelText(/^genre/i)).toHaveValue("synthwave")
    expect(screen.getByLabelText(/^bpm/i)).toHaveValue(122)
    expect(screen.getByLabelText(/^key/i)).toHaveValue("A minor")
    expect(screen.getByLabelText(/lyrics/i)).toHaveValue("neon lights")
  })

  it("lets the user edit a field (AC2)", async () => {
    const user = userEvent.setup()
    render(<DistributionForm clip={makeClip()} />)
    const album = screen.getByLabelText(/album/i)
    await user.type(album, "Night Sessions")
    expect(album).toHaveValue("Night Sessions")
  })

  it("highlights missing required fields on save (AC5)", async () => {
    const user = userEvent.setup()
    render(<DistributionForm clip={makeClip({ title: null, style_tags: [] })} />)
    await user.click(screen.getByRole("button", { name: /save draft/i }))
    const title = screen.getByLabelText(/^title/i)
    expect(title).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByText(/title is required/i)).toBeInTheDocument()
    expect(screen.getByText(/genre is required/i)).toBeInTheDocument()
  })

  it("generates a valid ISRC and UPC on demand (AC4)", async () => {
    const user = userEvent.setup()
    render(<DistributionForm clip={makeClip()} />)
    await user.click(screen.getByRole("button", { name: /generate isrc/i }))
    await user.click(screen.getByRole("button", { name: /generate upc/i }))
    expect((screen.getByLabelText(/isrc/i) as HTMLInputElement).value).toMatch(
      /^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$/
    )
    expect((screen.getByLabelText(/upc/i) as HTMLInputElement).value).toMatch(/^\d{12}$/)
  })

  it("saves a draft and resumes it on remount (AC6)", async () => {
    const user = userEvent.setup()
    const { unmount } = render(<DistributionForm clip={makeClip()} />)
    await user.clear(screen.getByLabelText(/album/i))
    await user.type(screen.getByLabelText(/album/i), "Night Sessions")
    await user.click(screen.getByRole("button", { name: /save draft/i }))

    expect(loadDraft("clip-1")?.album).toBe("Night Sessions")
    expect(screen.getByText(/draft saved/i)).toBeInTheDocument()

    unmount()
    render(<DistributionForm clip={makeClip()} />)
    expect(screen.getByLabelText(/album/i)).toHaveValue("Night Sessions")
  })

  it("rejects a non-image cover art file (AC3)", async () => {
    const user = userEvent.setup()
    render(<DistributionForm clip={makeClip()} />)
    const input = screen.getByLabelText(/upload cover art/i) as HTMLInputElement
    const pdf = new File(["x"], "cover.pdf", { type: "application/pdf" })
    await user.upload(input, pdf)
    expect(screen.getByText(/jpg or png/i)).toBeInTheDocument()
  })

  it("re-prefills when the selected song changes", () => {
    const { rerender } = render(<DistributionForm clip={makeClip()} />)
    expect(screen.getByLabelText(/^title/i)).toHaveValue("Midnight Drive")
    rerender(<DistributionForm clip={makeClip({ id: "clip-2", title: "Sunrise" })} />)
    expect(screen.getByLabelText(/^title/i)).toHaveValue("Sunrise")
  })

  it("surfaces a failure (not a crash) when storage can't save the draft", async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError")
    })
    render(<DistributionForm clip={makeClip()} />)
    await user.click(screen.getByRole("button", { name: /save draft/i }))
    expect(screen.getByRole("alert")).toHaveTextContent(/storage may be full/i)
    expect(screen.queryByText(/draft saved/i)).not.toBeInTheDocument()
    spy.mockRestore()
  })

  it("auto-saves the outgoing song's edits when the selected song changes (no data loss)", async () => {
    const user = userEvent.setup()
    const { rerender } = render(<DistributionForm clip={makeClip()} />)
    await user.type(screen.getByLabelText(/album/i), "Night Sessions")
    // Switch to another song without pressing Save…
    rerender(<DistributionForm clip={makeClip({ id: "clip-2", title: "Sunrise" })} />)
    expect(screen.getByLabelText(/^title/i)).toHaveValue("Sunrise")
    // …the edit was preserved as clip-1's draft and resumes on return.
    expect(loadDraft("clip-1")?.album).toBe("Night Sessions")
    rerender(<DistributionForm clip={makeClip()} />)
    expect(screen.getByLabelText(/album/i)).toHaveValue("Night Sessions")
  })

  it("backfills fields when resuming a draft written by an older version", () => {
    // A stale draft missing the nested `credits` object must not crash on read.
    localStorage.setItem(
      "ams:release-draft:clip-1",
      JSON.stringify({ title: "Legacy", album: "Old" })
    )
    render(<DistributionForm clip={makeClip()} />)
    expect(screen.getByLabelText(/^title/i)).toHaveValue("Legacy")
    expect(screen.getByLabelText(/album/i)).toHaveValue("Old")
    expect(screen.getByLabelText(/producer/i)).toHaveValue("") // backfilled, not undefined
  })

  it("keeps a live validation summary count of remaining required fields", async () => {
    const user = userEvent.setup()
    render(<DistributionForm clip={makeClip({ title: null, style_tags: [] })} />)
    await user.click(screen.getByRole("button", { name: /save draft/i }))
    // Two required fields missing (title, genre); artist has a placeholder default.
    const summary = screen.getByRole("alert")
    expect(within(summary).getByText(/2/)).toBeInTheDocument()
  })
})
