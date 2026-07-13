import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, useEffect, useRef } from "react"

import { AddTrackButton, TrackLane } from "./TrackLane"
import {
  StudioProvider,
  useStudio,
  type StudioAction,
} from "@/contexts/studio-context"
import { TRACK_STRIP_PX } from "@/lib/timeline"
import { TRACK_TYPES, type TrackType } from "@/lib/track-types"

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
  generationMode?: string | null
  clipBpm?: number | null
}

/** Seeds one track (t1) — optionally with clips — then renders TrackLane bound
 * to the live context state, so a dispatch from within TrackLane (rename, drop)
 * is immediately visible, the same way the real Studio page re-renders lanes
 * off `state.tracks`. */
function Harness({
  clips = [],
  trackType = "ai",
  snapOff = false,
  setup = [],
}: {
  clips?: SeedClip[]
  trackType?: TrackType
  snapOff?: boolean
  /** Extra actions dispatched after seeding (US-19.4 control state). */
  setup?: StudioAction[]
}) {
  return (
    <StudioProvider>
      <Seed clips={clips} trackType={trackType} snapOff={snapOff} setup={setup} />
    </StudioProvider>
  )
}

function Seed({
  clips,
  trackType,
  snapOff,
  setup,
}: {
  clips: SeedClip[]
  trackType: TrackType
  snapOff: boolean
  setup: StudioAction[]
}) {
  const { state, dispatch } = useStudio()
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    if (snapOff) dispatch({ type: "TOGGLE_SNAP" })
    dispatch({ type: "ADD_TRACK", id: "t1", trackType, name: "Track 1" })
    clips.forEach((c, i) => {
      dispatch({
        type: "ADD_CLIP",
        id: `seed-${i}`,
        trackId: "t1",
        clipId: c.clipId,
        startSec: c.startSec,
        title: c.title,
        durationSec: c.duration,
        generationMode: c.generationMode,
        clipBpm: c.clipBpm,
      })
    })
    for (const a of setup) dispatch(a)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const track = state.tracks.find((t) => t.id === "t1")
  if (!track) return null
  return (
    <>
      <TrackLane track={track} pxPerSec={20} token="tok" />
      <div data-testid="t1-probe">
        {JSON.stringify({
          volumeDb: track.volumeDb,
          pan: track.pan,
          muted: track.muted,
          solo: track.solo,
          color: track.color,
        })}
      </div>
    </>
  )
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

  it("sizes itself to the shared TRACK_STRIP_PX constant, not a hardcoded class value", () => {
    render(<Harness />)
    // Inline style, not just a Tailwind width class, so it can't silently
    // drift from the ruler spacer / playhead offset that share this constant.
    expect(screen.getByTestId("track-strip").style.width).toBe(
      `${TRACK_STRIP_PX}px`
    )
  })
})

describe("TrackLane per-track controls (US-19.4)", () => {
  const probe = () => JSON.parse(screen.getByTestId("t1-probe").textContent!)

  it("renders the volume fader at the track's level with the dB range", () => {
    render(<Harness />)
    const fader = screen.getByRole("slider", { name: "Track volume" })
    expect(fader).toHaveAttribute("aria-valuenow", "0")
    expect(fader).toHaveAttribute("aria-valuemin", "-60")
    expect(fader).toHaveAttribute("aria-valuemax", "6")
  })

  it("changes the track's volume from the fader keyboard", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const fader = screen.getByRole("slider", { name: "Track volume" })
    fader.focus()
    await user.keyboard("{ArrowDown}")
    expect(probe().volumeDb).toBe(-1)
    await user.keyboard("{Home}")
    expect(probe().volumeDb).toBe(-60)
  })

  it("changes the track's pan from the pan popover", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole("button", { name: "Track pan" }))
    const pan = screen.getByRole("slider", { name: "Pan" })
    expect(pan).toHaveAttribute("aria-valuenow", "0")
    pan.focus()
    await user.keyboard("{ArrowLeft}")
    expect(probe().pan).toBe(-1)
  })

  it("labels the pan trigger with the current position", () => {
    render(
      <Harness setup={[{ type: "SET_TRACK_PAN", trackId: "t1", pan: -100 }]} />
    )
    expect(screen.getByRole("button", { name: "Track pan" })).toHaveTextContent(
      "L100"
    )
  })

  it("mute toggles pressed state and dims the lane", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const mute = screen.getByRole("button", { name: "Mute track" })
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    expect(mute).toHaveAttribute("aria-pressed", "false")
    expect(region.className).not.toMatch(/opacity-50/)

    await user.click(mute)
    expect(mute).toHaveAttribute("aria-pressed", "true")
    expect(probe().muted).toBe(true)
    expect(region.className).toMatch(/opacity-50/)

    await user.click(mute)
    expect(probe().muted).toBe(false)
  })

  it("solo toggles pressed state", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const solo = screen.getByRole("button", { name: "Solo track" })
    await user.click(solo)
    expect(solo).toHaveAttribute("aria-pressed", "true")
    expect(probe().solo).toBe(true)
  })

  it("dims a non-soloed lane while another track is soloed", () => {
    render(
      <Harness
        setup={[
          { type: "ADD_TRACK", id: "t2", trackType: "ai" },
          { type: "TOGGLE_TRACK_SOLO", trackId: "t2" },
        ]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    expect(region.className).toMatch(/opacity-50/)
  })

  it("does not dim a soloed lane while solos are active", () => {
    render(
      <Harness
        setup={[
          { type: "ADD_TRACK", id: "t2", trackType: "ai" },
          { type: "TOGGLE_TRACK_SOLO", trackId: "t2" },
          { type: "TOGGLE_TRACK_SOLO", trackId: "t1" },
        ]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    expect(region.className).not.toMatch(/opacity-50/)
  })

  it("AI Regenerate opens a prompt dialog", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole("button", { name: "Regenerate track" }))
    expect(
      screen.getByRole("dialog", { name: /Regenerate/ })
    ).toBeInTheDocument()
  })

  it("disables regenerate on audio and vocal tracks (nothing to prompt-generate)", () => {
    render(<Harness trackType="audio" />)
    expect(
      screen.getByRole("button", { name: "Regenerate track" })
    ).toBeDisabled()
  })

  it("changes the track color from the swatch popover", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole("button", { name: "Track color" }))
    await user.click(screen.getByRole("button", { name: "Color Rose" }))
    expect(probe().color).toBe("#f43f5e")
    // Visually applied: the strip's accent border follows the track color.
    expect(screen.getByTestId("track-strip").style.borderLeft).toContain(
      "rgb(244, 63, 94)"
    )
    // Picking a color dismisses the popover (click-to-pick-and-dismiss).
    expect(
      screen.queryByRole("button", { name: "Color Rose" })
    ).not.toBeInTheDocument()
  })
})

describe("TrackLane track-type indicator (US-19.2)", () => {
  it("shows the track type's icon with an accessible label", () => {
    render(<Harness trackType="loop" />)
    expect(screen.getByLabelText("Sound/Loop track")).toBeInTheDocument()
  })

  it("accents the strip with the track type's color", () => {
    render(<Harness trackType="vocal" />)
    // jsdom normalizes hex to rgb(), so compare in that form.
    const [r, g, b] = [1, 3, 5].map((i) =>
      parseInt(TRACK_TYPES.vocal.color.slice(i, i + 2), 16)
    )
    expect(screen.getByTestId("track-strip").style.borderLeft).toContain(
      `rgb(${r}, ${g}, ${b})`
    )
  })
})

describe("AddTrackButton type selector (US-19.2)", () => {
  function MenuHarness() {
    return (
      <StudioProvider>
        <AddTrackButton />
        <TrackProbe />
      </StudioProvider>
    )
  }
  function TrackProbe() {
    const { state } = useStudio()
    return (
      <div data-testid="track-probe">
        {state.tracks.map((t) => t.trackType).join(",")}
      </div>
    )
  }

  it("offers all four track types and creates a track of the chosen type", async () => {
    const user = userEvent.setup()
    render(<MenuHarness />)
    await user.click(screen.getByRole("button", { name: /Add Track/i }))
    for (const label of ["AI-Generated", "Audio", "Sound/Loop", "Vocal"]) {
      expect(
        screen.getByRole("menuitem", { name: new RegExp(label) })
      ).toBeInTheDocument()
    }
    await user.click(screen.getByRole("menuitem", { name: /Sound\/Loop/ }))
    expect(screen.getByTestId("track-probe")).toHaveTextContent("loop")
  })

  it("can create every track type (US-19.2 acceptance)", async () => {
    const user = userEvent.setup()
    render(<MenuHarness />)
    for (const label of ["AI-Generated", "Audio", "Sound/Loop", "Vocal"]) {
      await user.click(screen.getByRole("button", { name: /Add Track/i }))
      await user.click(
        screen.getByRole("menuitem", { name: new RegExp(label) })
      )
    }
    expect(screen.getByTestId("track-probe")).toHaveTextContent(
      "ai,audio,loop,vocal"
    )
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
  Object.defineProperty(event, "clientX", {
    value: clientX,
    configurable: true,
  })
  Object.defineProperty(event, "dataTransfer", {
    value: dataTransfer,
    configurable: true,
  })
  return event
}

/** Same jsdom DragEvent gap as above, for `relatedTarget` — fireEvent.dragLeave
 * silently drops it too (verified by direct probe). */
function dragLeaveEventWithRelatedTarget(relatedTarget: EventTarget) {
  const event = new Event("dragleave", { bubbles: true, cancelable: true })
  Object.defineProperty(event, "relatedTarget", {
    value: relatedTarget,
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

  it("does not flicker the drag-over indicator when crossing into a child ClipBlock", () => {
    // A bare dragLeave fires when the pointer moves from the lane onto one of
    // its own ClipBlock children (still within the lane's box), not just when
    // it truly leaves the lane — guard on relatedTarget so it doesn't clear.
    render(
      <Harness
        clips={[{ clipId: "c1", title: "Intro", duration: 4, startSec: 0 }]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    const clipBlock = screen.getByTestId("clip-block")
    fireEvent.dragEnter(region)
    expect(region.className).toMatch(/bg-accent/)

    act(() => {
      region.dispatchEvent(dragLeaveEventWithRelatedTarget(clipBlock))
    })
    expect(region.className).toMatch(/bg-accent/)

    act(() => {
      region.dispatchEvent(dragLeaveEventWithRelatedTarget(document.body))
    })
    expect(region.className).not.toMatch(/bg-accent/)
  })

  it("rejects a drop whose clip type mismatches the track type (US-19.2)", () => {
    render(<Harness trackType="vocal" />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    fireEvent.drop(region, {
      dataTransfer: {
        getData: () =>
          JSON.stringify({
            kind: "add",
            clipId: "c1",
            title: "AI song",
            duration: 10,
            generationMode: "song",
          }),
      },
    })

    expect(screen.queryAllByTestId("clip-block")).toHaveLength(0)
  })

  it("marks the lane invalid during dragover of a mismatched clip type", () => {
    render(<Harness trackType="vocal" />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    fireEvent.dragEnter(region, {
      dataTransfer: { types: ["application/x-ams-track-type-ai"] },
    })
    expect(region.className).toMatch(/destructive/)
    expect(region.className).not.toMatch(/bg-accent/)
  })

  it("keeps the normal highlight during dragover of a matching clip type", () => {
    render(<Harness trackType="vocal" />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    fireEvent.dragEnter(region, {
      dataTransfer: { types: ["application/x-ams-track-type-vocal"] },
    })
    expect(region.className).toMatch(/bg-accent/)
    expect(region.className).not.toMatch(/destructive/)
  })

  it("only allows the native drop (preventDefault on dragover) for matching clip types", () => {
    // Not calling preventDefault on dragover is how the browser itself
    // disallows the drop and shows the no-drop cursor.
    render(<Harness trackType="vocal" />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })

    const mismatched = fireEvent.dragOver(region, {
      dataTransfer: { types: ["application/x-ams-track-type-ai"] },
    })
    expect(mismatched).toBe(true) // not prevented → drop disallowed

    const matching = fireEvent.dragOver(region, {
      dataTransfer: { types: ["application/x-ams-track-type-vocal"] },
    })
    expect(matching).toBe(false) // prevented → drop allowed
  })

  it("stretches a dropped loop clip to the project tempo (width from playbackRate)", async () => {
    // 90 BPM, 8s loop in a 120 BPM project → 4/3 rate → 6s × 20px = 120px.
    render(<Harness trackType="loop" />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    fireEvent.drop(region, {
      dataTransfer: {
        getData: () =>
          JSON.stringify({
            kind: "add",
            clipId: "c1",
            title: "Loop",
            duration: 8,
            generationMode: "sound",
            bpm: 90,
          }),
      },
    })

    await waitFor(() =>
      expect(screen.getByTestId("clip-block").style.width).toBe("120px")
    )
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
        getData: () => JSON.stringify({ kind: "move", placementId: "seed-0" }),
      },
    })

    await waitFor(() =>
      expect(screen.getAllByTestId("clip-block")).toHaveLength(1)
    )
    expect(screen.getByText("Intro")).toBeInTheDocument()
  })

  // The drop keeps the grabbed point under the cursor: left edge lands
  // grabOffsetSec before the cursor's timeline position.
  it("subtracts the move payload's grab offset from the drop position", async () => {
    render(
      <Harness
        clips={[{ clipId: "c1", title: "Intro", duration: 4, startSec: 0 }]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    // Cursor at 100px = 5s (20 px/sec); grabbed 2s into the clip → left edge
    // lands at 3s = 60px.
    region.dispatchEvent(
      dropEventWithClientX(100, {
        getData: () =>
          JSON.stringify({
            kind: "move",
            placementId: "seed-0",
            grabOffsetSec: 2,
          }),
      })
    )

    await waitFor(() =>
      expect(screen.getByTestId("clip-block")).toHaveStyle({ left: "60px" })
    )
  })
})

describe("TrackLane snap-to-grid (US-19.3)", () => {
  // Defaults: snap on, 1-beat resolution, 120 BPM → 0.5s grid = 10px at 20px/s.
  it("quantizes an added clip's drop position to the nearest grid line", async () => {
    render(<Harness />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    // 17px = 0.85s → nearest beat is 1.0s → 20px.
    region.dispatchEvent(
      dropEventWithClientX(17, {
        getData: () =>
          JSON.stringify({ kind: "add", clipId: "c1", title: "A", duration: 4 }),
      })
    )
    await waitFor(() =>
      expect(screen.getByTestId("clip-block")).toHaveStyle({ left: "20px" })
    )
  })

  it("leaves the drop position untouched when snap is disabled", async () => {
    render(<Harness snapOff />)
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    region.dispatchEvent(
      dropEventWithClientX(17, {
        getData: () =>
          JSON.stringify({ kind: "add", clipId: "c1", title: "A", duration: 4 }),
      })
    )
    await waitFor(() =>
      expect(screen.getByTestId("clip-block")).toHaveStyle({ left: "17px" })
    )
  })

  it("quantizes a moved clip's landing position", async () => {
    render(
      <Harness
        clips={[{ clipId: "c1", title: "Intro", duration: 4, startSec: 0 }]}
      />
    )
    const region = screen.getByRole("region", { name: "Track 1 timeline" })
    vi.spyOn(region, "getBoundingClientRect").mockReturnValue(zeroRect())

    // Cursor 47px, grabbed 1s (20px) into the clip → raw left edge 27px =
    // 1.35s → snaps to 1.5s = 30px.
    region.dispatchEvent(
      dropEventWithClientX(47, {
        getData: () =>
          JSON.stringify({ kind: "move", placementId: "seed-0", grabOffsetSec: 1 }),
      })
    )
    await waitFor(() =>
      expect(screen.getByTestId("clip-block")).toHaveStyle({ left: "30px" })
    )
  })

  it("renders grid lines on the lane when snap is enabled, none when disabled", () => {
    const { unmount } = render(<Harness />)
    expect(
      screen.getByRole("region", { name: "Track 1 timeline" }).style
        .backgroundImage
    ).toContain("repeating-linear-gradient")
    unmount()

    render(<Harness snapOff />)
    expect(
      screen.getByRole("region", { name: "Track 1 timeline" }).style
        .backgroundImage
    ).toBe("")
  })
})
