import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { VideoProgress } from "@/components/video/VideoProgress"
import type { VideoJobState } from "@/hooks/use-video-job"

function renderState(state: VideoJobState) {
  const onRetry = vi.fn()
  const onReset = vi.fn()
  render(<VideoProgress state={state} onRetry={onRetry} onReset={onReset} />)
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
      detail: { job_id: "j1", status: "encoding", progress: 90 },
    })
    expect(screen.getByRole("status")).toHaveTextContent(/encoding video/i)
  })

  it("shows completion with a reset affordance", () => {
    const { onReset } = renderState({
      phase: "complete",
      detail: { job_id: "j1", status: "complete", progress: 100, video_id: "v1" },
    })
    expect(screen.getByRole("status")).toHaveTextContent(/ready/i)
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
