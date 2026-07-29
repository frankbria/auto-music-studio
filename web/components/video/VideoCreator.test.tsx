import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { VideoCreator } from "@/components/video/VideoCreator"
import type { VideoJobState } from "@/hooks/use-video-job"
import type { Clip } from "@/lib/workspace-clips"

vi.mock("@/hooks/use-require-auth", () => ({
  useRequireAuth: () => ({ isLoading: false, isAuthenticated: true }),
}))

const clip = {
  id: "c1",
  workspace_id: "w1",
  title: "Neon Nights",
  duration: 120,
  style_tags: [],
  parent_clip_ids: [],
  is_public: false,
  created_at: "2026-01-01T00:00:00Z",
} as unknown as Clip

let clipResult: { clip: Clip | null; loading: boolean; notFound: boolean }
vi.mock("@/hooks/use-clip", () => ({
  useClip: () => clipResult,
}))

let jobState: VideoJobState
const submit = vi.fn()
vi.mock("@/hooks/use-video-job", () => ({
  useVideoJob: () => ({ state: jobState, submit, retry: vi.fn(), reset: vi.fn() }),
}))

const track = vi.fn()
vi.mock("@/contexts/video-jobs-context", () => ({
  useVideoJobs: () => ({ track }),
}))

// Sibling components own their behavior tests; stub them to isolate composition.
vi.mock("@/components/video/SourceSongCard", () => ({
  SourceSongCard: ({ clip: c }: { clip: Clip }) => (
    <div data-testid="source-card">{c.title}</div>
  ),
}))
vi.mock("@/components/video/VideoForm", () => ({
  VideoForm: ({ onGenerate }: { onGenerate: (c: unknown) => void }) => (
    <button onClick={() => onGenerate({ prompt: "x" })}>mock-generate</button>
  ),
}))

beforeEach(() => {
  clipResult = { clip, loading: false, notFound: false }
  jobState = { phase: "idle" }
})

afterEach(() => vi.clearAllMocks())

describe("VideoCreator", () => {
  it("renders the source card and the form for a loaded song", () => {
    render(<VideoCreator songId="c1" />)
    expect(screen.getByTestId("source-card")).toHaveTextContent("Neon Nights")
    expect(screen.getByRole("button", { name: "mock-generate" })).toBeInTheDocument()
  })

  it("submits the config for the routed song id", () => {
    render(<VideoCreator songId="c1" />)
    fireEvent.click(screen.getByRole("button", { name: "mock-generate" }))
    expect(submit).toHaveBeenCalledWith("c1", { prompt: "x" })
  })

  it("swaps the form for the progress view once a job is running", () => {
    jobState = {
      phase: "polling",
      jobId: "j1",
      detail: { job_id: "j1", status: "rendering", progress: 10 },
    }
    render(<VideoCreator songId="c1" />)
    expect(
      screen.queryByRole("button", { name: "mock-generate" })
    ).not.toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(/rendering/i)
  })

  it("registers a running job with the app-level watcher for cross-nav notifications", () => {
    jobState = { phase: "polling", jobId: "job-42" }
    render(<VideoCreator songId="c1" />)
    expect(track).toHaveBeenCalledWith({ jobId: "job-42", songId: "c1" })
  })

  it("does not track while idle", () => {
    jobState = { phase: "idle" }
    render(<VideoCreator songId="c1" />)
    expect(track).not.toHaveBeenCalled()
  })

  it("shows a loading state while the song loads", () => {
    clipResult = { clip: null, loading: true, notFound: false }
    render(<VideoCreator songId="c1" />)
    expect(screen.getByRole("status")).toHaveTextContent(/loading song/i)
  })

  it("shows not-found for an unknown song", () => {
    clipResult = { clip: null, loading: false, notFound: true }
    render(<VideoCreator songId="nope" />)
    expect(screen.getByText(/song not found/i)).toBeInTheDocument()
  })
})
