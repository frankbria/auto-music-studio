import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { VideoForm } from "@/components/video/VideoForm"
import type { Clip } from "@/lib/workspace-clips"

let tier = { tier: "free", isFreeTier: true, isLoading: false }
vi.mock("@/hooks/use-subscription-tier", () => ({
  useSubscriptionTier: () => tier,
}))

const clip = {
  id: "c1",
  workspace_id: "w1",
  title: "Neon Nights",
  format: "wav",
  duration: 120,
  bpm: 120,
  key: "C",
  style_tags: ["synthwave"],
  lyrics: null,
  vocal_language: null,
  model: null,
  seed: null,
  inference_steps: null,
  parent_clip_ids: [],
  generation_mode: null,
  is_public: false,
  created_at: "2026-01-01T00:00:00Z",
} as Clip

function renderForm(onGenerate = vi.fn(), c: Clip = clip) {
  render(<VideoForm clip={c} onGenerate={onGenerate} />)
  return onGenerate
}

beforeEach(() => {
  tier = { tier: "free", isFreeTier: true, isLoading: false }
  // Unique URL per call, like the real API — previews are keyed/removed by URL.
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn((f: File) => `blob:${f.name}`),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("VideoForm", () => {
  it("renders every configuration control", () => {
    renderForm()
    expect(screen.getByLabelText(/style prompt/i)).toBeInTheDocument()
    expect(screen.getByRole("group", { name: /style preset/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/reference images/i)).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: /lyrics sync/i })).toBeInTheDocument()
    expect(screen.getByRole("radiogroup", { name: /aspect ratio/i })).toBeInTheDocument()
    expect(screen.getByRole("radiogroup", { name: /resolution/i })).toBeInTheDocument()
    expect(screen.getByRole("radiogroup", { name: /frame rate/i })).toBeInTheDocument()
    expect(screen.getByRole("radiogroup", { name: /transitions/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /generate video/i })).toBeInTheDocument()
  })

  it("keeps Generate disabled until a prompt or preset is chosen", () => {
    const onGenerate = renderForm()
    const generate = screen.getByRole("button", { name: /generate video/i })
    expect(generate).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/style prompt/i), {
      target: { value: "neon skyline" },
    })
    expect(generate).toBeEnabled()

    fireEvent.click(generate)
    expect(onGenerate).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt: "neon skyline",
        lyrics_sync: false,
        aspect_ratio: "16:9",
        resolution: "720p",
        frame_rate: 30,
        transitions: "auto",
      })
    )
    // No hosted image URLs exist (no upload endpoint) — must not send any.
    expect(onGenerate.mock.calls[0][0].reference_image_urls).toBeUndefined()
  })

  it("selecting a preset populates the prompt and enables Generate", () => {
    const onGenerate = renderForm()
    fireEvent.click(screen.getByRole("button", { name: /cinematic/i }))

    const prompt = screen.getByLabelText(/style prompt/i) as HTMLTextAreaElement
    expect(prompt.value).toMatch(/cinematic film scenes/i)

    const generate = screen.getByRole("button", { name: /generate video/i })
    expect(generate).toBeEnabled()
    fireEvent.click(generate)
    expect(onGenerate).toHaveBeenCalledWith(
      expect.objectContaining({ style_preset: "cinematic" })
    )
  })

  it("shows a Pro badge and disables 1080p/4K for free users, with upgrade copy", () => {
    renderForm()
    const resolutions = screen.getByRole("radiogroup", { name: /resolution/i })
    expect(within(resolutions).getByRole("radio", { name: /720p/i })).toBeEnabled()
    expect(within(resolutions).getByRole("radio", { name: /1080p/i })).toBeDisabled()
    expect(within(resolutions).getByRole("radio", { name: /4k/i })).toBeDisabled()
    expect(within(resolutions).getAllByText("Pro")).toHaveLength(2)
    expect(screen.getByText(/upgrade to pro/i)).toBeInTheDocument()
  })

  it("lets Pro users select every resolution and aspect ratio combination", () => {
    tier = { tier: "pro", isFreeTier: false, isLoading: false }
    const onGenerate = renderForm()
    fireEvent.change(screen.getByLabelText(/style prompt/i), {
      target: { value: "x" },
    })
    expect(screen.queryByText(/upgrade to pro/i)).not.toBeInTheDocument()

    const aspects = screen.getByRole("radiogroup", { name: /aspect ratio/i })
    const resolutions = screen.getByRole("radiogroup", { name: /resolution/i })
    // Accessible names are the full labels ("16:9 Landscape", "1080p Pro", …).
    const aspectName: Record<string, RegExp> = {
      "16:9": /^16:9/,
      "9:16": /^9:16/,
      "1:1": /^1:1/,
    }
    for (const aspect of ["16:9", "9:16", "1:1"]) {
      for (const res of ["720p", "1080p", "4K"]) {
        fireEvent.click(
          within(aspects).getByRole("radio", { name: aspectName[aspect] })
        )
        fireEvent.click(within(resolutions).getByRole("radio", { name: new RegExp(`^${res}`, "i") }))
        fireEvent.click(screen.getByRole("button", { name: /generate video/i }))
        expect(onGenerate).toHaveBeenLastCalledWith(
          expect.objectContaining({
            aspect_ratio: aspect,
            resolution: res === "4K" ? "4k" : res,
          })
        )
      }
    }
    expect(onGenerate).toHaveBeenCalledTimes(9)
  })

  it("shows the credit estimate and updates it with resolution and duration", () => {
    tier = { tier: "pro", isFreeTier: false, isLoading: false }
    renderForm()
    expect(screen.getByText(/estimated cost/i)).toHaveTextContent("5 credits")

    const resolutions = screen.getByRole("radiogroup", { name: /resolution/i })
    fireEvent.click(within(resolutions).getByRole("radio", { name: /1080p/i }))
    expect(screen.getByText(/estimated cost/i)).toHaveTextContent("7 credits")
  })

  it("adds the long-song surcharge to the estimate", () => {
    renderForm(vi.fn(), { ...clip, duration: 200 })
    expect(screen.getByText(/estimated cost/i)).toHaveTextContent("7 credits")
  })

  it("accepts up to five reference images with removable previews", () => {
    renderForm()
    const input = screen.getByLabelText(/reference images/i)
    const img = (n: string) => new File(["x"], n, { type: "image/png" })

    fireEvent.change(input, { target: { files: [img("a.png"), img("b.png")] } })
    expect(screen.getAllByRole("img", { name: /reference/i })).toHaveLength(2)

    fireEvent.click(screen.getAllByRole("button", { name: /remove/i })[0])
    expect(screen.getAllByRole("img", { name: /reference/i })).toHaveLength(1)
  })

  it("rejects more than five reference images and non-image files", () => {
    renderForm()
    const input = screen.getByLabelText(/reference images/i)
    const img = (n: string) => new File(["x"], n, { type: "image/png" })

    fireEvent.change(input, {
      target: {
        files: [img("1"), img("2"), img("3"), img("4"), img("5"), img("6")],
      },
    })
    expect(screen.getByText(/up to 5 reference images/i)).toBeInTheDocument()
    expect(screen.queryAllByRole("img", { name: /reference/i })).toHaveLength(0)

    // The input remounts (key bump) after every selection so the same files can
    // be re-picked — re-query rather than reusing the detached node.
    fireEvent.change(screen.getByLabelText(/reference images/i), {
      target: { files: [new File(["x"], "doc.pdf", { type: "application/pdf" })] },
    })
    expect(screen.getByText(/image files only/i)).toBeInTheDocument()
  })

  it("revokes preview object URLs on unmount", () => {
    const { unmount } = render(<VideoForm clip={clip} onGenerate={vi.fn()} />)
    const input = screen.getByLabelText(/reference images/i)
    fireEvent.change(input, {
      target: { files: [new File(["x"], "a.png", { type: "image/png" })] },
    })
    expect(screen.getAllByRole("img", { name: /reference/i })).toHaveLength(1)

    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:a.png")
  })

  it("caps the style prompt at the backend limit", () => {
    renderForm()
    const prompt = screen.getByLabelText(/style prompt/i)
    expect(prompt).toHaveAttribute("maxlength", "2000")
  })

})
