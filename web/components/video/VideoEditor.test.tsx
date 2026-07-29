import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { VideoEditor } from "@/components/video/VideoEditor"
import { fetchVideoVersions, submitVideoEdit } from "@/lib/video"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

// Keep the pure helpers (editOperationLabel, videoStreamUrl); stub the network.
vi.mock("@/lib/video", async (orig) => ({
  ...(await orig<typeof import("@/lib/video")>()),
  submitVideoEdit: vi.fn(),
  fetchVideoVersions: vi.fn(),
}))

const submitMock = vi.mocked(submitVideoEdit)
const versionsMock = vi.mocked(fetchVideoVersions)

afterEach(() => vi.clearAllMocks())

const VERSIONS = [
  {
    id: "v2",
    clip_id: "c",
    job_id: "j",
    resolution: "1080p",
    aspect_ratio: "16:9",
    published: false,
    created_at: "2026-07-29T00:00:00Z",
    parent_video_id: "v1",
    edit: { operation: "trim" as const },
  },
  {
    id: "v1",
    clip_id: "c",
    job_id: "j",
    resolution: "1080p",
    aspect_ratio: "16:9",
    published: false,
    created_at: "2026-07-28T00:00:00Z",
  },
]

describe("VideoEditor", () => {
  it("lists the version history with edit labels and view/download links", async () => {
    versionsMock.mockResolvedValue(VERSIONS)
    render(<VideoEditor videoId="v1" />)

    const list = await screen.findByTestId("version-list")
    expect(list).toHaveTextContent("Trim")
    expect(list).toHaveTextContent("Original render")
    // The original stays reachable via its stream URL.
    const views = screen.getAllByRole("link", { name: /view/i })
    expect(
      views.some((a) => a.getAttribute("href") === "/api/videos/v1/stream")
    ).toBe(true)
    expect(versionsMock).toHaveBeenCalledWith("v1", "tok")
  })

  it("submits a trim edit with the typed payload and shows it queued", async () => {
    versionsMock.mockResolvedValue([])
    submitMock.mockResolvedValue({ status: "accepted", jobId: "job-1" })
    render(<VideoEditor videoId="v1" />)

    fireEvent.change(screen.getByLabelText(/start/i), {
      target: { value: "2" },
    })
    fireEvent.change(screen.getByLabelText(/end/i), { target: { value: "8" } })
    fireEvent.click(screen.getByRole("button", { name: /apply edit/i }))

    await waitFor(() =>
      expect(submitMock).toHaveBeenCalledWith(
        "v1",
        { operation: "trim", start_seconds: 2, end_seconds: 8 },
        "tok"
      )
    )
    expect(await screen.findByRole("status")).toHaveTextContent(/queued/i)
  })

  it("blocks an invalid trim range client-side without submitting", async () => {
    versionsMock.mockResolvedValue([])
    render(<VideoEditor videoId="v1" />)

    fireEvent.change(screen.getByLabelText(/start/i), {
      target: { value: "9" },
    })
    fireEvent.change(screen.getByLabelText(/end/i), { target: { value: "3" } })
    fireEvent.click(screen.getByRole("button", { name: /apply edit/i }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/after start/i)
    expect(submitMock).not.toHaveBeenCalled()
  })

  it("submits a lyrics_overlay toggle", async () => {
    versionsMock.mockResolvedValue([])
    submitMock.mockResolvedValue({ status: "accepted", jobId: "job-2" })
    render(<VideoEditor videoId="v1" />)

    fireEvent.change(screen.getByLabelText(/^edit$/i), {
      target: { value: "lyrics_overlay" },
    })
    fireEvent.click(screen.getByRole("button", { name: /apply edit/i }))

    await waitFor(() =>
      expect(submitMock).toHaveBeenCalledWith(
        "v1",
        { operation: "lyrics_overlay", lyrics_enabled: true },
        "tok"
      )
    )
  })

  it("parses transition markers from the comma-separated field", async () => {
    versionsMock.mockResolvedValue([])
    submitMock.mockResolvedValue({ status: "accepted", jobId: "job-3" })
    render(<VideoEditor videoId="v1" />)

    fireEvent.change(screen.getByLabelText(/^edit$/i), {
      target: { value: "transitions" },
    })
    fireEvent.change(screen.getByLabelText(/cut points/i), {
      target: { value: "4, 8.5, 12" },
    })
    fireEvent.click(screen.getByRole("button", { name: /apply edit/i }))

    await waitFor(() =>
      expect(submitMock).toHaveBeenCalledWith(
        "v1",
        { operation: "transitions", transition_markers: [4, 8.5, 12] },
        "tok"
      )
    )
  })

  it("surfaces an insufficient-credits error", async () => {
    versionsMock.mockResolvedValue([])
    submitMock.mockResolvedValue({
      status: "insufficient_credits",
      balance: 3,
      required: 7,
    })
    render(<VideoEditor videoId="v1" />)

    fireEvent.change(screen.getByLabelText(/start/i), {
      target: { value: "0" },
    })
    fireEvent.change(screen.getByLabelText(/end/i), { target: { value: "5" } })
    fireEvent.click(screen.getByRole("button", { name: /apply edit/i }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /not enough credits/i
    )
  })
})
