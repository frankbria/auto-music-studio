import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { VideoProgress } from "@/components/video/VideoProgress"
import type { VideoJobState } from "@/hooks/use-video-job"

// VideoDelivery owns its own behavior tests; stub it so this suite covers only
// the state→view routing and captures the props the complete branch forwards.
vi.mock("@/components/video/VideoDelivery", () => ({
  VideoDelivery: ({
    videoId,
    songId,
    onReset,
  }: {
    videoId: string
    songId: string
    onReset: () => void
  }) => (
    <button data-testid="delivery" data-video={videoId} data-song={songId} onClick={onReset}>
      delivery
    </button>
  ),
}))

function renderState(state: VideoJobState) {
  const onRetry = vi.fn()
  const onReset = vi.fn()
  render(
    <VideoProgress state={state} songId="song-1" onRetry={onRetry} onReset={onReset} />
  )
  return { onRetry, onReset }
}

describe("VideoProgress", () => {
  it("shows a submitting spinner at 0%", () => {
    renderState({ phase: "submitting" })
    expect(screen.getByRole("status")).toHaveTextContent(/submitting/i)
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0")
  })

  it("shows the rendering state with progress and ETA", () => {
    renderState({
      phase: "polling",
      jobId: "j1",
      detail: { job_id: "j1", status: "rendering", progress: 42, eta_seconds: 120 },
    })
    expect(screen.getByRole("status")).toHaveTextContent(/rendering scenes/i)
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42")
    expect(screen.getByText(/42%/)).toBeInTheDocument()
    expect(screen.getByText(/~2 min remaining/)).toBeInTheDocument()
  })

  it("shows the encoding state", () => {
    renderState({
      phase: "polling",
      jobId: "j1",
      detail: { job_id: "j1", status: "encoding", progress: 90 },
    })
    expect(screen.getByRole("status")).toHaveTextContent(/encoding video/i)
  })

  it("renders the delivery view on completion, wired to the video and song", () => {
    const { onReset } = renderState({
      phase: "complete",
      detail: { job_id: "j1", status: "complete", progress: 100, video_id: "v1" },
    })
    const delivery = screen.getByTestId("delivery")
    expect(delivery).toHaveAttribute("data-video", "v1")
    expect(delivery).toHaveAttribute("data-song", "song-1")
    fireEvent.click(delivery)
    expect(onReset).toHaveBeenCalled()
  })

  it("falls back to a reset affordance if a completed job has no video id", () => {
    const { onReset } = renderState({
      phase: "complete",
      detail: { job_id: "j1", status: "complete", progress: 100 },
    })
    expect(screen.queryByTestId("delivery")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /generate another/i }))
    expect(onReset).toHaveBeenCalled()
  })

  it("shows errors with Retry and Back to settings", () => {
    const { onRetry, onReset } = renderState({
      phase: "error",
      message: "render died",
    })
    expect(screen.getByRole("alert")).toHaveTextContent("render died")
    fireEvent.click(screen.getByRole("button", { name: /retry/i }))
    expect(onRetry).toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: /back to settings/i }))
    expect(onReset).toHaveBeenCalled()
  })
})
