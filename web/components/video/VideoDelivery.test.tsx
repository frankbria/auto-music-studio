import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { VideoDelivery } from "@/components/video/VideoDelivery"
import { publishVideo } from "@/lib/video"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

// Keep videoStreamUrl real (a pure URL builder); stub only the network call.
vi.mock("@/lib/video", async (orig) => ({
  ...(await orig<typeof import("@/lib/video")>()),
  publishVideo: vi.fn(),
}))

const publishMock = vi.mocked(publishVideo)

afterEach(() => vi.clearAllMocks())

describe("VideoDelivery", () => {
  it("plays the rendered video and links the MP4 download", () => {
    render(<VideoDelivery videoId="v1" songId="s1" onReset={vi.fn()} />)

    const player = screen.getByTestId("video-delivery-player")
    expect(player).toHaveAttribute("src", "/api/videos/v1/stream")

    const download = screen.getByRole("link", { name: /download mp4/i })
    expect(download).toHaveAttribute("href", "/api/videos/v1/stream?download=1")
    expect(download).toHaveAttribute("download")
  })

  it("publishes and then links to the song page", async () => {
    publishMock.mockResolvedValue({
      status: "published",
      video: {
        id: "v1",
        clip_id: "s1",
        job_id: "j1",
        resolution: "1080p",
        aspect_ratio: "16:9",
        published: true,
        created_at: "2026-07-01T00:00:00Z",
      },
    })
    render(<VideoDelivery videoId="v1" songId="s1" onReset={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: /publish to song page/i }))
    expect(publishMock).toHaveBeenCalledWith("v1", "tok")

    const link = await screen.findByRole("link", { name: /view on song page/i })
    expect(link).toHaveAttribute("href", "/song/s1")
    expect(screen.getByText(/it now appears on the song page/i)).toBeInTheDocument()
  })

  it("surfaces a publish error", async () => {
    publishMock.mockResolvedValue({ status: "error", detail: "Publishing failed. Please try again." })
    render(<VideoDelivery videoId="v1" songId="s1" onReset={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: /publish to song page/i }))
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/publishing failed/i)
    )
    // Still publishable — the button stays (no false "published" state).
    expect(screen.getByRole("button", { name: /publish to song page/i })).toBeInTheDocument()
  })

  it("resets to generate another", () => {
    const onReset = vi.fn()
    render(<VideoDelivery videoId="v1" songId="s1" onReset={onReset} />)
    fireEvent.click(screen.getByRole("button", { name: /generate another/i }))
    expect(onReset).toHaveBeenCalled()
  })
})
