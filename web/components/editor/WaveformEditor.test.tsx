import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { WaveformEditor } from "./WaveformEditor"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import type { ClipAudio } from "@/lib/audio-peaks"
import type { Clip } from "@/lib/workspace-clips"

// jsdom reports clientWidth as 0, so the viewport never initializes. Stub a real
// width so the canvas + controls render like they do in a browser.
let widthSpy: PropertyDescriptor | undefined
beforeEach(() => {
  widthSpy = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth")
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 800,
  })
})
afterEach(() => {
  if (widthSpy) Object.defineProperty(HTMLElement.prototype, "clientWidth", widthSpy)
})

function fakeClip(): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "Test Clip",
    duration: 10,
    bpm: 120,
  } as Clip
}

function fakeAudio(): ClipAudio {
  return { mono: new Float32Array(800), sampleRate: 8000, duration: 10 }
}

/** Surfaces player state so tests can assert the editor drives it. */
function Probe() {
  const { state } = usePlayer()
  return (
    <div>
      <span data-testid="current-id">{state.current?.id ?? "none"}</span>
      <span data-testid="seek-req">{state.seekRequest ?? "null"}</span>
    </div>
  )
}

function renderEditor() {
  return render(
    <PlayerProvider>
      <WaveformEditor clip={fakeClip()} audio={fakeAudio()} />
      <Probe />
    </PlayerProvider>
  )
}

function canvas() {
  return screen.getByRole("img", { name: "Waveform" })
}
function pxPerSec() {
  return Number(canvas().getAttribute("data-px-per-sec"))
}

describe("WaveformEditor", () => {
  it("loads the clip into the player so the playhead/seek use the real engine", () => {
    renderEditor()
    expect(screen.getByTestId("current-id")).toHaveTextContent("c1")
  })

  it("opens at the full-clip fit zoom (800px / 10s = 80 px/sec)", () => {
    renderEditor()
    expect(pxPerSec()).toBe(80)
  })

  it("zooms in and back to fit", async () => {
    renderEditor()
    const start = pxPerSec()
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }))
    expect(pxPerSec()).toBeGreaterThan(start)
    fireEvent.click(screen.getByRole("button", { name: "Fit to view" }))
    expect(pxPerSec()).toBe(start)
  })

  it("disables zoom-out and fit at the fit floor", () => {
    renderEditor()
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Fit to view" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeEnabled()
  })

  it("seeks the player when the waveform is clicked (no drag)", () => {
    renderEditor()
    // At fit, 80 px/sec: clicking at x=160 seeks to 2s.
    fireEvent.pointerDown(canvas(), { clientX: 160, pointerId: 1 })
    fireEvent.pointerUp(canvas(), { clientX: 160, pointerId: 1 })
    expect(Number(screen.getByTestId("seek-req").textContent)).toBeCloseTo(2, 1)
  })

  it("hides the scrollbar at fit (nothing to scroll) and shows it when zoomed in", () => {
    renderEditor()
    expect(
      screen.queryByRole("slider", { name: "Scroll waveform" })
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }))
    expect(
      screen.getByRole("slider", { name: "Scroll waveform" })
    ).toBeInTheDocument()
  })
})
