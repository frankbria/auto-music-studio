import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { useEffect, useRef } from "react"

import { RulerArea } from "./RulerArea"
import { StudioProvider, useStudio } from "@/contexts/studio-context"

// 20 px/sec throughout; default snap (1 beat @ 120 BPM = 0.5s) is a 10px grid.
const PX_PER_SEC = 20

function Harness({
  markers = [],
  loop = null,
  snapOff = false,
  bpm,
  resolution,
}: {
  markers?: { id: string; sec: number; label: string }[]
  loop?: { startSec: number; endSec: number } | null
  snapOff?: boolean
  bpm?: number
  resolution?: "1bar" | "1beat" | "1/2beat" | "1/4beat"
}) {
  return (
    <StudioProvider>
      <Seed
        markers={markers}
        loop={loop}
        snapOff={snapOff}
        bpm={bpm}
        resolution={resolution}
      />
    </StudioProvider>
  )
}

function Seed({
  markers,
  loop,
  snapOff,
  bpm,
  resolution,
}: {
  markers: { id: string; sec: number; label: string }[]
  loop: { startSec: number; endSec: number } | null
  snapOff: boolean
  bpm?: number
  resolution?: "1bar" | "1beat" | "1/2beat" | "1/4beat"
}) {
  const { dispatch } = useStudio()
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    if (snapOff) dispatch({ type: "TOGGLE_SNAP" })
    if (bpm != null) dispatch({ type: "SET_BPM", bpm })
    if (resolution) dispatch({ type: "SET_SNAP_RESOLUTION", resolution })
    for (const m of markers) dispatch({ type: "ADD_MARKER", ...m })
    if (loop) {
      dispatch({ type: "SET_LOOP_REGION", ...loop })
      dispatch({ type: "TOGGLE_LOOP" })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return <RulerArea pxPerSec={PX_PER_SEC} durationSec={60} />
}

function mockAreaRect() {
  const area = screen.getByTestId("ruler-area")
  vi.spyOn(area, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    right: 1200,
    bottom: 40,
    width: 1200,
    height: 40,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  return area
}

describe("RulerArea markers (US-19.3)", () => {
  it("renders a labeled flag for each marker at its timeline position", () => {
    render(
      <Harness markers={[{ id: "m1", sec: 4, label: "Verse 1" }]} />
    )
    const flag = screen.getByRole("button", { name: "Marker: Verse 1" })
    expect(flag).toHaveStyle({ left: "80px" })
    expect(flag).toHaveTextContent("Verse 1")
  })

  it("adds a snapped marker on double-click", () => {
    render(<Harness />)
    const area = mockAreaRect()
    // 17px = 0.85s → snaps to 1s → 20px.
    fireEvent.doubleClick(area, { clientX: 17 })
    const flag = screen.getByRole("button", { name: "Marker: Marker 1" })
    expect(flag).toHaveStyle({ left: "20px" })
  })

  it("adds a marker at the raw position when snap is off", () => {
    render(<Harness snapOff />)
    const area = mockAreaRect()
    fireEvent.doubleClick(area, { clientX: 17 })
    expect(screen.getByRole("button", { name: "Marker: Marker 1" })).toHaveStyle(
      { left: "17px" }
    )
  })

  it("renames a marker through the flag's editor", async () => {
    const user = userEvent.setup()
    render(<Harness markers={[{ id: "m1", sec: 4, label: "Verse 1" }]} />)
    await user.click(screen.getByRole("button", { name: "Marker: Verse 1" }))
    const input = screen.getByRole("textbox", { name: "Marker label" })
    await user.clear(input)
    await user.type(input, "Chorus")
    await user.click(screen.getByRole("button", { name: "Rename" }))
    expect(
      screen.getByRole("button", { name: "Marker: Chorus" })
    ).toBeInTheDocument()
  })

  it("deletes a marker through the flag's editor", async () => {
    const user = userEvent.setup()
    render(<Harness markers={[{ id: "m1", sec: 4, label: "Verse 1" }]} />)
    await user.click(screen.getByRole("button", { name: "Marker: Verse 1" }))
    await user.click(screen.getByRole("button", { name: "Delete" }))
    expect(
      screen.queryByRole("button", { name: "Marker: Verse 1" })
    ).not.toBeInTheDocument()
  })

  it("drags a marker to a new snapped position", () => {
    render(<Harness markers={[{ id: "m1", sec: 4, label: "Verse 1" }]} />)
    mockAreaRect()
    const flag = screen.getByRole("button", { name: "Marker: Verse 1" })
    fireEvent.pointerDown(flag, { clientX: 80, pointerId: 1 })
    // 97px = 4.85s → snaps to 5s → 100px.
    fireEvent.pointerMove(flag, { clientX: 97, pointerId: 1 })
    fireEvent.pointerUp(flag, { pointerId: 1 })
    expect(flag).toHaveStyle({ left: "100px" })
  })
})

describe("RulerArea loop region (US-19.3)", () => {
  it("renders nothing for the loop when it is disabled", () => {
    render(<Harness />)
    expect(screen.queryByTestId("loop-region")).not.toBeInTheDocument()
  })

  it("highlights the loop range when enabled", () => {
    render(<Harness loop={{ startSec: 2, endSec: 6 }} />)
    const region = screen.getByTestId("loop-region")
    expect(region).toHaveStyle({ left: "40px", width: "80px" })
  })

  it("drags the loop end handle to a new snapped position", () => {
    render(<Harness loop={{ startSec: 2, endSec: 6 }} />)
    mockAreaRect()
    const handle = screen.getByRole("slider", { name: "Loop end handle" })
    fireEvent.pointerDown(handle, { clientX: 120, pointerId: 1 })
    // 97px = 4.85s → snaps to 5s: region becomes 2s..5s = 40px..100px.
    fireEvent.pointerMove(handle, { clientX: 97, pointerId: 1 })
    fireEvent.pointerUp(handle, { pointerId: 1 })
    expect(screen.getByTestId("loop-region")).toHaveStyle({
      left: "40px",
      width: "60px",
    })
  })

  it("normalizes handles dragged across each other", () => {
    render(<Harness loop={{ startSec: 2, endSec: 6 }} />)
    mockAreaRect()
    const handle = screen.getByRole("slider", { name: "Loop start handle" })
    fireEvent.pointerDown(handle, { clientX: 40, pointerId: 1 })
    // Start handle dragged past the end (8s > 6s) → region stays normalized 6..8.
    fireEvent.pointerMove(handle, { clientX: 160, pointerId: 1 })
    fireEvent.pointerUp(handle, { pointerId: 1 })
    expect(screen.getByTestId("loop-region")).toHaveStyle({
      left: "120px",
      width: "40px",
    })
  })
})

describe("RulerArea review fixes (US-19.3)", () => {
  it("clamps a marker dragged past the timeline end to durationSec", () => {
    render(<Harness markers={[{ id: "m1", sec: 4, label: "Verse 1" }]} />)
    mockAreaRect()
    const flag = screen.getByRole("button", { name: "Marker: Verse 1" })
    fireEvent.pointerDown(flag, { clientX: 80, pointerId: 1 })
    // Way past the 60s timeline (60s × 20px = 1200px).
    fireEvent.pointerMove(flag, { clientX: 5000, pointerId: 1 })
    fireEvent.pointerUp(flag, { pointerId: 1 })
    expect(flag).toHaveStyle({ left: "1200px" })
  })

  it("loop handles expose their range and adjust with arrow keys", () => {
    render(<Harness loop={{ startSec: 2, endSec: 6 }} />)
    const handle = screen.getByRole("slider", { name: "Loop end handle" })
    expect(handle).toHaveAttribute("aria-valuemin", "0")
    expect(handle).toHaveAttribute("aria-valuemax", "60")
    // Default snap step is 0.5s (1 beat @ 120 BPM): 6s → 5.5s → 70px wide.
    fireEvent.keyDown(handle, { key: "ArrowLeft" })
    expect(screen.getByTestId("loop-region")).toHaveStyle({ width: "70px" })
    fireEvent.keyDown(handle, { key: "ArrowRight" })
    expect(screen.getByTestId("loop-region")).toHaveStyle({ width: "80px" })
  })
})

describe("RulerArea PR-review fixes (US-19.3, claude-review)", () => {
  it("never snaps a marker past the timeline end", () => {
    // 1 bar @ 90 BPM = 2.667s: 60s clamps then rounds UP to 61.33s without a
    // post-snap clamp. The marker must stay at 60s = 1200px.
    render(
      <Harness
        markers={[{ id: "m1", sec: 4, label: "V" }]}
        bpm={90}
        resolution="1bar"
      />
    )
    mockAreaRect()
    const flag = screen.getByRole("button", { name: "Marker: V" })
    fireEvent.pointerDown(flag, { clientX: 80, pointerId: 1 })
    fireEvent.pointerMove(flag, { clientX: 5000, pointerId: 1 })
    fireEvent.pointerUp(flag, { pointerId: 1 })
    expect(flag).toHaveStyle({ left: "1200px" })
  })

  it("a cancelled marker drag stops tracking pointer movement", () => {
    render(<Harness markers={[{ id: "m1", sec: 4, label: "V" }]} />)
    mockAreaRect()
    const flag = screen.getByRole("button", { name: "Marker: V" })
    fireEvent.pointerDown(flag, { clientX: 80, pointerId: 1 })
    fireEvent.pointerCancel(flag, { pointerId: 1 })
    // A hover after the cancel must not move the marker.
    fireEvent.pointerMove(flag, { clientX: 300, pointerId: 1 })
    expect(flag).toHaveStyle({ left: "80px" })
  })

  it("a cancelled loop-handle drag stops tracking pointer movement", () => {
    render(<Harness loop={{ startSec: 2, endSec: 6 }} />)
    mockAreaRect()
    const handle = screen.getByRole("slider", { name: "Loop end handle" })
    fireEvent.pointerDown(handle, { clientX: 120, pointerId: 1 })
    fireEvent.pointerCancel(handle, { pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 300, pointerId: 1 })
    expect(screen.getByTestId("loop-region")).toHaveStyle({ width: "80px" })
  })
})
