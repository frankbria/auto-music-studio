import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MasteringTab } from "@/components/mastering/mastering-tab"
import type { MasteringJobState } from "@/hooks/use-mastering-job"
import type { UseMasteringPreviews } from "@/hooks/use-mastering-previews"
import type { Clip } from "@/lib/workspace-clips"

// --- hook/lib mocks -------------------------------------------------------
const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

let jobState: MasteringJobState
const submit = vi.fn()
const retry = vi.fn()
const reset = vi.fn()
// Capture the onComplete the tab passes so a test can fire it (the real hook
// invokes it once, from its poll loop, when a job reaches completed).
let capturedOnComplete: ((detail: unknown) => void) | undefined
vi.mock("@/hooks/use-mastering-job", () => ({
  useMasteringJob: (opts?: { onComplete?: (detail: unknown) => void }) => {
    capturedOnComplete = opts?.onComplete
    return { state: jobState, submit, retry, reset }
  },
}))

let previewsResult: UseMasteringPreviews
vi.mock("@/hooks/use-mastering-previews", () => ({
  useMasteringPreviews: () => previewsResult,
}))

vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: "tok" }) }))

const notify = vi.fn()
vi.mock("@/contexts/notifications-context", () => ({ useNotify: () => notify }))

const approveMasteringPreview = vi.fn()
vi.mock("@/lib/mastering", async (orig) => {
  const actual = await orig<typeof import("@/lib/mastering")>()
  return { ...actual, approveMasteringPreview: (...a: unknown[]) => approveMasteringPreview(...a) }
})

function clip(id: string): Clip {
  return {
    id,
    workspace_id: "w1",
    title: id,
    format: "wav",
    duration: 60,
    bpm: null,
    key: null,
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: null,
    is_public: false,
    created_at: "2026-01-01",
  }
}

const readyPreviews: UseMasteringPreviews = {
  state: {
    status: "ready",
    data: {
      source_clip_id: "c1",
      original_audio_url: "orig",
      original_metrics: { loudness: -20 },
      previews: [
        { preview_id: "m1", audio_url: "u1", profile: "streaming", service: "dolby", loudness_delta: 6, metrics: { loudness: -14 } },
      ],
    },
  },
  selectedId: "m1",
  select: vi.fn(),
  reload: vi.fn(),
}

afterEach(() => vi.clearAllMocks())

describe("MasteringTab", () => {
  it("prompts to select a song when none is chosen", () => {
    jobState = { phase: "idle" }
    previewsResult = { state: { status: "loading" }, selectedId: null, select: vi.fn(), reload: vi.fn() }
    render(<MasteringTab selectedClip={null} />)
    expect(screen.getByText(/select a song above/i)).toBeInTheDocument()
  })

  it("renders the config panel and submits for the selected clip", async () => {
    jobState = { phase: "idle" }
    previewsResult = { state: { status: "loading" }, selectedId: null, select: vi.fn(), reload: vi.fn() }
    const user = userEvent.setup()
    render(<MasteringTab selectedClip={clip("c1")} />)

    await user.click(screen.getByRole("button", { name: /start mastering/i }))
    expect(submit).toHaveBeenCalledWith("c1", { profile: "streaming", service: "dolby", format: "wav" })
  })

  it("shows progress while polling", () => {
    jobState = { phase: "polling", detail: { job_id: "j1", status: "processing" } }
    previewsResult = { state: { status: "loading" }, selectedId: null, select: vi.fn(), reload: vi.fn() }
    render(<MasteringTab selectedClip={clip("c1")} />)
    expect(screen.getByRole("status")).toHaveTextContent(/processing/i)
  })

  it("shows a failure with a working retry", async () => {
    jobState = { phase: "error", message: "boom" }
    previewsResult = { state: { status: "loading" }, selectedId: null, select: vi.fn(), reload: vi.fn() }
    const user = userEvent.setup()
    render(<MasteringTab selectedClip={clip("c1")} />)

    expect(screen.getByRole("alert")).toHaveTextContent("boom")
    await user.click(screen.getByRole("button", { name: /retry/i }))
    expect(retry).toHaveBeenCalled()
  })

  it("shows previews, the A/B player, and approves a master", async () => {
    jobState = { phase: "completed", detail: { job_id: "j1", status: "completed" } }
    previewsResult = readyPreviews
    approveMasteringPreview.mockResolvedValue({ status: "approved", clipId: "m1", audioUrl: "u" })
    const user = userEvent.setup()
    render(<MasteringTab selectedClip={clip("c1")} />)

    // Preview list + A/B player render.
    expect(screen.getByLabelText(/mastered previews/i)).toBeInTheDocument()
    expect(screen.getByTestId("preview-audio")).toHaveAttribute("src", "/api/clips/m1/stream")

    await user.click(screen.getByRole("button", { name: /approve master/i }))
    expect(approveMasteringPreview).toHaveBeenCalledWith("j1", "m1", "tok")
    await waitFor(() => expect(screen.getByText(/master approved/i)).toBeInTheDocument())
    // The approval confirmation carries the "Mastered" badge.
    expect(
      screen.getByText("Mastered", { selector: "[data-slot='badge']" })
    ).toBeInTheDocument()
  })

  it("re-shows Approve after approving one preview and selecting another", async () => {
    jobState = { phase: "completed", detail: { job_id: "j1", status: "completed" } }
    // Two candidates; start with m1 selected.
    const two: UseMasteringPreviews = {
      state: {
        status: "ready",
        data: {
          source_clip_id: "c1",
          previews: [
            { preview_id: "m1", audio_url: "u1", loudness_delta: 6 },
            { preview_id: "m2", audio_url: "u2", loudness_delta: 3 },
          ],
        },
      },
      selectedId: "m1",
      select: vi.fn(),
      reload: vi.fn(),
    }
    previewsResult = two
    approveMasteringPreview.mockResolvedValue({ status: "approved", clipId: "x", audioUrl: "u" })
    const user = userEvent.setup()
    const { rerender } = render(<MasteringTab selectedClip={clip("c1")} />)

    await user.click(screen.getByRole("button", { name: /approve master/i }))
    await waitFor(() =>
      expect(screen.getByText("Mastered", { selector: "[data-slot='badge']" })).toBeInTheDocument()
    )

    // The user now selects a different candidate to keep comparing.
    previewsResult = { ...two, selectedId: "m2" }
    rerender(<MasteringTab selectedClip={clip("c1")} />)

    // The approval banner is gone; Approve is offered for the new selection.
    expect(screen.queryByText("Mastered", { selector: "[data-slot='badge']" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /approve master/i })).toBeInTheDocument()
    // And the top status pill no longer contradicts it: it falls back to
    // "Preview ready" for the newly-selected, unapproved candidate (review #1).
    expect(screen.getByRole("status")).toHaveTextContent(/preview ready/i)
  })

  it("raises a mastering_complete notification when a job completes (AC5)", () => {
    jobState = { phase: "completed", detail: { job_id: "j1", status: "completed" } }
    previewsResult = readyPreviews
    render(<MasteringTab selectedClip={clip("Velvet Static")} />)

    // The tab wires notify() through the hook's onComplete; firing it notifies.
    act(() => capturedOnComplete?.({ job_id: "j1", status: "completed" }))
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: "mastering_complete" })
    )
    // A distinct "Preview ready" status shows for the completed-not-approved job (AC2).
    // Scope to the status role — the history section below also lists a preview_ready row.
    expect(screen.getByRole("status")).toHaveTextContent(/preview ready/i)
  })

  it("redirects to login when approval is unauthorized", async () => {
    jobState = { phase: "completed", detail: { job_id: "j1", status: "completed" } }
    previewsResult = readyPreviews
    approveMasteringPreview.mockResolvedValue({ status: "unauthorized" })
    const user = userEvent.setup()
    render(<MasteringTab selectedClip={clip("c1")} />)

    await user.click(screen.getByRole("button", { name: /approve master/i }))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"))
  })
})
