import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ClipBlock } from "./ClipBlock"
import { parseClipDragData, readDragTrackType } from "@/lib/clip-drag"
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

  it("compresses its width by the playback rate (loop tempo inheritance, US-19.2)", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    const { getByTestId } = render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
        playbackRate={4 / 3}
      />
    )
    // 8s of audio at 4/3 speed occupies 6s of timeline → 120px.
    expect(getByTestId("clip-block").style.width).toBe("120px")
  })

  it("renders a null-duration clip at a visible minimum width, not a 1px sliver", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    const { getByTestId } = render(
      <ClipBlock
        placement={{ ...placement, durationSec: null }}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    const width = parseFloat(getByTestId("clip-block").style.width)
    // Wide enough to show a truncated title and stay selectable/draggable.
    expect(width).toBeGreaterThanOrEqual(40)
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

describe("ClipBlock drag source (reposition via MOVE_CLIP)", () => {
  it("is draggable and sets a 'move' drag payload naming its own placement", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
      />
    )
    const block = screen.getByTestId("clip-block")
    expect(block).toHaveAttribute("draggable", "true")

    const store = new Map<string, string>()
    const dataTransfer = {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? "",
    } as unknown as DataTransfer
    fireEvent.dragStart(block, { dataTransfer })

    // jsdom's zero-rect + missing clientX both read as 0, so the grab offset
    // computes to 0 here; the offset math itself is asserted in TrackLane's
    // grab-offset drop test.
    expect(parseClipDragData(dataTransfer)).toEqual({
      kind: "move",
      placementId: "p1",
      grabOffsetSec: 0,
    })
  })

  it("marks the drag with its track's type so lanes can validate during dragover (US-19.2)", () => {
    getClipAudioMock.mockReturnValue(new Promise(() => {}))
    render(
      <ClipBlock
        placement={placement}
        pxPerSec={20}
        color="#123456"
        token="tok"
        trackType="vocal"
      />
    )
    const store = new Map<string, string>()
    const dataTransfer = {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? "",
      get types() {
        return [...store.keys()]
      },
    } as unknown as DataTransfer
    fireEvent.dragStart(screen.getByTestId("clip-block"), { dataTransfer })

    expect(readDragTrackType(dataTransfer)).toBe("vocal")
  })
})
