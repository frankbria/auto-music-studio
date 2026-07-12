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

describe("TrackLane drop zone", () => {
  it("accepts a dropped clip and adds it at the dropped position", async () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    fireEvent.drop(region, {
      dataTransfer: {
        getData: () =>
          JSON.stringify({ clipId: "c1", title: "Dropped", duration: 10 }),
      },
      clientX: 100, // 100px / 20px-per-sec = 5s
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
})
