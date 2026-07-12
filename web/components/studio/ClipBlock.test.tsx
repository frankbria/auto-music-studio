import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ClipBlock } from "./ClipBlock"
import type { Placement } from "@/lib/timeline"

const { getClipAudioMock } = vi.hoisted(() => ({
  getClipAudioMock: vi.fn(),
}))

vi.mock("@/lib/clip-audio-cache", () => ({
  getClipAudio: getClipAudioMock,
}))

const placement: Placement = {
  id: "p1",
  clipId: "clip-a",
  startSec: 4,
  title: "My Clip",
  durationSec: 8,
}

afterEach(() => {
  getClipAudioMock.mockReset()
})

describe("ClipBlock layout", () => {
  it("positions and sizes itself from startSec/durationSec and pxPerSec", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {})) // never resolves
    const { getByTestId } = render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    const block = getByTestId("clip-block")
    expect(block.style.left).toBe("80px") // 4s * 20px/sec
    expect(block.style.width).toBe("160px") // 8s * 20px/sec
  })

  it("renders the clip title, truncated via CSS", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    expect(screen.getByText("My Clip")).toBeInTheDocument()
  })

  it("falls back to a placeholder title when the clip has none", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    render(
      <ClipBlock
        placement={{ ...placement, title: null }}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    expect(screen.getByText("Untitled clip")).toBeInTheDocument()
  })
})

describe("ClipBlock waveform thumbnail", () => {
  it("fetches decoded audio for the clip via the shared cache", async () => {
    getClipAudioMock.mockResolvedValue({
      buffer: {} as AudioBuffer,
      peaks: new Float32Array([0.2, 0.5, 0.9]),
      duration: 8,
    })
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    await waitFor(() =>
      expect(getClipAudioMock).toHaveBeenCalledWith("clip-a", "tok")
    )
  })

  it("does not fetch audio without a token", () => {
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token={null}
      />
    )
    expect(getClipAudioMock).not.toHaveBeenCalled()
  })

  it("survives a failed decode without crashing", async () => {
    getClipAudioMock.mockRejectedValue(new Error("boom"))
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    await waitFor(() => expect(getClipAudioMock).toHaveBeenCalled())
    expect(screen.getByText("My Clip")).toBeInTheDocument()
  })
})
