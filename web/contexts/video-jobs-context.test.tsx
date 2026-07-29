import { act, render } from "@testing-library/react"
import { useEffect } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { VideoJobsProvider, useVideoJobs } from "@/contexts/video-jobs-context"
import { fetchVideoStatus } from "@/lib/video"

const notify = vi.fn()

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))
vi.mock("@/contexts/notifications-context", () => ({
  useNotify: () => notify,
}))
vi.mock("@/lib/video", () => ({
  fetchVideoStatus: vi.fn(),
}))

const statusMock = vi.mocked(fetchVideoStatus)

function Tracker({ jobId, songId }: { jobId: string; songId: string }) {
  const { track } = useVideoJobs()
  useEffect(() => {
    track({ jobId, songId })
  }, [track, jobId, songId])
  return null
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
  vi.clearAllMocks()
})

async function tick(ms = 3000) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe("VideoJobsProvider", () => {
  it("notifies on completion for a tracked job, then stops polling it", async () => {
    statusMock.mockResolvedValue({
      kind: "complete",
      detail: { job_id: "j1", status: "complete", progress: 100, video_id: "v1" },
    })
    render(
      <VideoJobsProvider>
        <Tracker jobId="j1" songId="s1" />
      </VideoJobsProvider>
    )

    await tick() // first poll fires at 3s
    expect(statusMock).toHaveBeenCalledWith("j1", "tok")
    expect(notify).toHaveBeenCalledWith({
      type: "video_complete",
      message: "Your music video is ready.",
      href: "/video/s1",
    })

    // Completed jobs are dropped from the watch list — no further polling.
    statusMock.mockClear()
    await tick()
    expect(statusMock).not.toHaveBeenCalled()
  })

  it("stops watching a failed job without a notification", async () => {
    statusMock.mockResolvedValue({ kind: "failed", error: "render died" })
    render(
      <VideoJobsProvider>
        <Tracker jobId="j2" songId="s2" />
      </VideoJobsProvider>
    )

    await tick()
    expect(statusMock).toHaveBeenCalledWith("j2", "tok")
    expect(notify).not.toHaveBeenCalled()

    statusMock.mockClear()
    await tick()
    expect(statusMock).not.toHaveBeenCalled()
  })

  it("keeps polling a still-rendering job", async () => {
    statusMock.mockResolvedValue({
      kind: "pending",
      detail: { job_id: "j3", status: "rendering", progress: 20 },
    })
    render(
      <VideoJobsProvider>
        <Tracker jobId="j3" songId="s3" />
      </VideoJobsProvider>
    )

    await tick()
    await tick()
    expect(statusMock.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(notify).not.toHaveBeenCalled()
  })
})
