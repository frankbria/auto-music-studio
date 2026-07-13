import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useEffect, useRef } from "react"

import { TrackLane } from "./TrackLane"
import { StudioProvider, useStudio } from "@/contexts/studio-context"

const { getClipAudioMock } = vi.hoisted(() => ({
  getClipAudioMock: vi.fn(),
}))
vi.mock("@/lib/clip-audio-cache", () => ({
  getClipAudio: getClipAudioMock,
}))

type SeedClip = {
  clipId: string
  title: string
  duration: number
  startSec: number
}

/** Seeds one track (t1) — optionally with clips — then renders TrackLane bound
 * to the live context state, so a dispatch from within TrackLane (rename, drop)
 * is immediately visible, the same way the real Studio page re-renders lanes
 * off `state.tracks`. */
function Harness({ clips = [] }: { clips?: SeedClip[] }) {
  return (
    <StudioProvider>
      <Seed clips={clips} />
    </StudioProvider>
  )
}

function Seed({ clips }: { clips: SeedClip[] }) {
  const { state, dispatch } = useStudio()
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    dispatch({ type: "ADD_TRACK", id: "t1", name: "Track 1" })
    clips.forEach((c, i) => {
      dispatch({
        type: "ADD_CLIP",
        id: `seed-${i}`,
        trackId: "t1",
        clipId: c.clipId,
        startSec: c.startSec,
        title: c.title,
        durationSec: c.duration,
      })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const track = state.tracks.find((t) => t.id === "t1")
  if (!track) return null
  return <TrackLane track={track} pxPerSec={20} token="tok" />
}

afterEach(() => {
  getClipAudioMock.mockReset()
  getClipAudioMock.mockReturnValue(new Promise(() => {}))
})

describe("TrackLane control strip", () => {
  it("shows the track name", () => {
    render(<Harness />)
    expect(screen.getByText("Track 1")).toBeInTheDocument()
  })

  it("renames the track on commit", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole("button", { name: "Edit track name" }))
    const input = screen.getByRole("textbox", { name: "Track name" })
    await user.clear(input)
    await user.type(input, "Drums")
    await user.tab() // blur commits
    expect(screen.getByText("Drums")).toBeInTheDocument()
  })

  it("Escape cancels the edit without renaming", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole("button", { name: "Edit track name" }))
    const input = screen.getByRole("textbox", { name: "Track name" })
    await user.clear(input)
    await user.type(input, "Drums{Escape}")
    expect(screen.getByText("Track 1")).toBeInTheDocument()
    expect(screen.queryByText("Drums")).not.toBeInTheDocument()
  })
})

describe("TrackLane clips", () => {
  it("renders a ClipBlock for each clip on the track", () => {
    render(
      <Harness
        clips={[{ clipId: "c1", title: "Intro", duration: 4, startSec: 0 }]}
      />
    )
    expect(screen.getByText("Intro")).toBeInTheDocument()
  })
})

function zeroRect() {
  return {
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }
}

/** jsdom has no DragEvent, so fireEvent.drop's `clientX` init is silently
 * dropped (verified by direct probe) — dispatch a plain Event with clientX
 * and dataTransfer overridden via defineProperty instead, which React's
 * synthetic event does read through. */
function dropEventWithClientX(clientX: number, dataTransfer: unknown) {
  const event = new Event("drop", { bubbles: true, cancelable: true })
  Object.defineProperty(event, "clientX", { value: clientX, configurable: true })
  Object.defineProperty(event, "dataTransfer", {
    value: dataTransfer,
    configurable: true,
  })
  return event
}

describe("TrackLane drop zone — adding a new clip", () => {
  it("accepts a dropped clip and adds it to the track", async () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    fireEvent.drop(region, {
      dataTransfer: {
        getData: () =>
          JSON.stringify({
            kind: "add",
            clipId: "c1",
            title: "Dropped",
            duration: 10,
          }),
      },
    })

    await waitFor(() => expect(screen.getByText("Dropped")).toBeInTheDocument())
  })

  it("ignores a drop with no parseable payload", () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    const before = screen.queryAllByTestId("clip-block").length
    fireEvent.drop(region, { dataTransfer: { getData: () => "" } })
    expect(screen.queryAllByTestId("clip-block").length).toBe(before)
  })

  it("shows a drag-over indicator while a drag hovers the lane", () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    expect(region.className).not.toMatch(/bg-accent/)
    fireEvent.dragEnter(region)
    expect(region.className).toMatch(/bg-accent/)
    fireEvent.dragLeave(region)
    expect(region.className).not.toMatch(/bg-accent/)
  })

  it("clamps a drop left of the lane's origin to startSec 0", async () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    // Lane starts at x=100 on screen; the drop lands at x=20 — 80px to the
    // left of the lane's own origin, which would be a negative startSec
    // without the Math.max(0, …) clamp.
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue({
      ...zeroRect(),
      left: 100,
    })

    region.dispatchEvent(
      dropEventWithClientX(20, {
        getData: () =>
          JSON.stringify({
            kind: "add",
            clipId: "c1",
            title: "Dropped",
            duration: 10,
          }),
      })
    )

    await waitFor(() => {
      const block = screen.getByTestId("clip-block")
      expect(block.style.left).toBe("0px")
    })
  })
})

describe("TrackLane drop zone — repositioning an existing clip", () => {
  // jsdom has no native DragEvent, so fireEvent.drop can't carry a real
  // clientX through to the handler (verified against RTL's DragEvent
  // fallback) — the pixel math itself is covered by lib/timeline.test.ts's
  // xToSec tests. This exercises the MOVE_CLIP branch selection: a "move"
  // payload must reposition the existing placement, never duplicate it.
  it("routes a 'move' payload to MOVE_CLIP instead of adding a duplicate", async () => {
    render(
      <Harness
        clips={[{ clipId: "c1", title: "Intro", duration: 4, startSec: 0 }]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    fireEvent.drop(region, {
      dataTransfer: {
        getData: () =>
          JSON.stringify({
            kind: "move",
            placementId: "seed-0",
            sourceTrackId: "t1",
          }),
      },
    })

    await waitFor(() =>
      expect(screen.getAllByTestId("clip-block")).toHaveLength(1)
    )
    expect(screen.getByText("Intro")).toBeInTheDocument()
  })
})
