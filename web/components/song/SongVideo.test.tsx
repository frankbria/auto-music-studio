import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SongVideo } from "@/components/song/SongVideo"
import { fetchPublishedVideoForClip } from "@/lib/video"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

vi.mock("@/lib/video", async (orig) => ({
  ...(await orig<typeof import("@/lib/video")>()),
  fetchPublishedVideoForClip: vi.fn(),
}))

const fetchMock = vi.mocked(fetchPublishedVideoForClip)

afterEach(() => vi.clearAllMocks())

describe("SongVideo", () => {
  it("renders the published video for the clip", async () => {
    fetchMock.mockResolvedValue({
      id: "v1",
      clip_id: "c1",
      job_id: "j1",
      resolution: "1080p",
      aspect_ratio: "16:9",
      published: true,
      created_at: "2026-07-01T00:00:00Z",
    })
    render(<SongVideo clipId="c1" />)

    const player = await screen.findByTestId("song-video-player")
    expect(player).toHaveAttribute("src", "/api/videos/v1/stream")
    expect(screen.getByRole("region", { name: /music video/i })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith("c1", "tok")
  })

  it("renders nothing when the clip has no published video", async () => {
    fetchMock.mockResolvedValue(null)
    const { container } = render(<SongVideo clipId="c1" />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.queryByTestId("song-video-player")).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})
