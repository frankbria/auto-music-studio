import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { WaveformEditor } from "./WaveformEditor"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import type { ClipAudio } from "@/lib/audio-peaks"
import type { Clip } from "@/lib/workspace-clips"

// The always-mounted SaveVersionModal reads the auth context; stub it so the
// editor renders without an AuthProvider (the modal stays closed here — its own
// submit flow is covered in editing/SaveVersionModal tests).
vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}))

// Repaint (US-18.5) reuses the real submit→poll pipeline; mock only its network
// edges so a completed job flows back into the editor's undo stack. importActual
// keeps the rest of these modules (SaveVersionModal's saveClipVersion, the real
// peak helpers) intact.
const submitRepaint = vi.fn()
const decodeClipAudio = vi.fn()
const fetchJobStatus = vi.fn()
vi.mock("@/lib/editing", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/editing")>()),
  submitRepaint: (...args: unknown[]) => submitRepaint(...args),
}))
vi.mock("@/lib/audio-peaks", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/audio-peaks")>()),
  decodeClipAudio: (...args: unknown[]) => decodeClipAudio(...args),
}))
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

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
  vi.clearAllMocks()
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

// 800 samples @ 80Hz = exactly 10s, so removeRegion/insertRegion recompute a
// duration consistent with the fixture (mono.length / sampleRate).
function fakeAudio(): ClipAudio {
  return { mono: new Float32Array(800), sampleRate: 80, duration: 10 }
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
/** At fit (80 px/sec, scrollSec 0) drag from `fromSec` to `toSec` to select. */
function dragSelect(fromSec: number, toSec: number) {
  fireEvent.pointerDown(canvas(), { clientX: fromSec * 80, pointerId: 1 })
  fireEvent.pointerMove(canvas(), { clientX: toSec * 80, pointerId: 1 })
  fireEvent.pointerUp(canvas(), { clientX: toSec * 80, pointerId: 1 })
}
function editedDuration() {
  return Number(
    document.querySelector("[data-edited-duration]")?.getAttribute("data-edited-duration")
  )
}
function opCount() {
  return Number(
    document.querySelector("[data-op-count]")?.getAttribute("data-op-count")
  )
}
function key(k: string, opts: { ctrlKey?: boolean; shiftKey?: boolean } = {}) {
  fireEvent.keyDown(document.body, { key: k, ...opts })
}
function undoBtn() {
  return screen.getByRole("button", { name: "Undo" })
}
function redoBtn() {
  return screen.getByRole("button", { name: "Redo" })
}
function saveBtn() {
  return screen.getByRole("button", { name: /Save as new version/i })
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

  it("shows the selection info and overlay after a click-and-drag", () => {
    renderEditor()
    expect(screen.queryByTestId("selection-info")).not.toBeInTheDocument()
    dragSelect(2, 5)
    expect(screen.getByTestId("selection-overlay")).toBeInTheDocument()
    expect(screen.getByTestId("selection-info")).toHaveTextContent("Duration 0:03.000")
  })

  it("Delete removes the selected region and shortens the audio", () => {
    renderEditor()
    expect(editedDuration()).toBeCloseTo(10)
    dragSelect(2, 5) // 3s region
    key("Delete")
    expect(editedDuration()).toBeCloseTo(7)
    expect(screen.queryByTestId("selection-info")).not.toBeInTheDocument() // cleared
  })

  it("Ctrl+C then Ctrl+V duplicates the region at the playhead (lengthens audio)", () => {
    renderEditor()
    dragSelect(2, 5) // 3s region
    key("c", { ctrlKey: true })
    key("v", { ctrlKey: true }) // playhead at 0 → inserts 3s at the start
    expect(editedDuration()).toBeCloseTo(13)
    // seek moved the playhead to the end of the pasted region (3s).
    expect(Number(screen.getByTestId("seek-req").textContent)).toBeCloseTo(3, 1)
  })

  it("paste clamps the playhead into the edited timeline", () => {
    renderEditor()
    dragSelect(2, 5) // 3s clipboard
    key("c", { ctrlKey: true })
    // Move the playhead to 8s (clears the selection; the clipboard persists).
    fireEvent.pointerDown(canvas(), { clientX: 8 * 80, pointerId: 1 })
    fireEvent.pointerUp(canvas(), { clientX: 8 * 80, pointerId: 1 })
    key("v", { ctrlKey: true }) // insert 3s at 8s → new duration 13, playhead 11
    expect(editedDuration()).toBeCloseTo(13)
    expect(Number(screen.getByTestId("seek-req").textContent)).toBeCloseTo(11, 1)
  })

  it("a drag that collapses back to its origin creates no selection", () => {
    renderEditor()
    fireEvent.pointerDown(canvas(), { clientX: 240, pointerId: 1 })
    fireEvent.pointerMove(canvas(), { clientX: 300, pointerId: 1 }) // sweep out
    fireEvent.pointerMove(canvas(), { clientX: 240, pointerId: 1 }) // back to origin
    fireEvent.pointerUp(canvas(), { clientX: 240, pointerId: 1 })
    expect(screen.queryByTestId("selection-info")).not.toBeInTheDocument()
  })

  it("Ctrl+X copies then removes (clipboard filled, audio shortened)", () => {
    renderEditor()
    dragSelect(2, 5)
    key("x", { ctrlKey: true })
    expect(editedDuration()).toBeCloseTo(7)
    // 3s @ 80Hz = 240 samples now on the clipboard, ready to paste.
    expect(
      document.querySelector("[data-clipboard-samples]")?.getAttribute("data-clipboard-samples")
    ).toBe("240")
  })

  // --- Processing toolbar (US-18.3) ----------------------------------------

  it("Fade In records an op and keeps the duration, then clears the selection", () => {
    renderEditor()
    dragSelect(2, 5)
    fireEvent.click(screen.getByRole("button", { name: "Fade In" }))
    expect(opCount()).toBe(1)
    expect(editedDuration()).toBeCloseTo(10) // amplitude-only, no length change
    expect(screen.queryByTestId("selection-info")).not.toBeInTheDocument()
  })

  it("Silence keeps the length (unlike Delete which removes samples)", () => {
    renderEditor()
    dragSelect(2, 5)
    fireEvent.click(screen.getByRole("button", { name: "Silence" }))
    expect(editedDuration()).toBeCloseTo(10)
    expect(opCount()).toBe(1)
  })

  it("Normalize works on the whole clip when nothing is selected", () => {
    renderEditor()
    expect(screen.queryByTestId("selection-info")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Normalize" }))
    expect(opCount()).toBe(1) // whole-clip fallback, no selection required
  })

  it("Gain applies to the selection and records an op", () => {
    renderEditor()
    dragSelect(2, 5)
    fireEvent.click(screen.getByRole("button", { name: "Gain" }))
    fireEvent.click(screen.getByRole("button", { name: "Apply gain" }))
    expect(opCount()).toBe(1)
    expect(editedDuration()).toBeCloseTo(10) // amplitude-only
  })

  it("Crossfade at the clip start no-ops and logs nothing (no-fit guard)", () => {
    renderEditor()
    // Playhead sits at 0 (no real audio in jsdom), so the window can't fit and
    // the guard must skip the commit — no ghost op in the save seam.
    fireEvent.click(screen.getByRole("button", { name: "Crossfade" }))
    fireEvent.click(screen.getByRole("button", { name: "Apply crossfade" }))
    expect(opCount()).toBe(0)
    expect(editedDuration()).toBeCloseTo(10)
  })

  it("region tools are disabled until there is a selection", () => {
    renderEditor()
    expect(screen.getByRole("button", { name: "Fade In" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Gain" })).toBeDisabled()
    dragSelect(2, 5)
    expect(screen.getByRole("button", { name: "Fade In" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Gain" })).toBeEnabled()
  })

  // --- Undo / redo + save (US-18.4) ----------------------------------------

  it("undo reverts the last edit and redo re-applies it", () => {
    renderEditor()
    dragSelect(2, 5) // 3s region
    key("Delete")
    expect(editedDuration()).toBeCloseTo(7)
    expect(opCount()).toBe(1)

    fireEvent.click(undoBtn())
    expect(editedDuration()).toBeCloseTo(10) // original restored
    expect(opCount()).toBe(0)

    fireEvent.click(redoBtn())
    expect(editedDuration()).toBeCloseTo(7) // edit re-applied
    expect(opCount()).toBe(1)
  })

  it("multiple undos walk back through the full operation history", () => {
    renderEditor()
    dragSelect(2, 5) // delete 3s → 7
    key("Delete")
    const afterFirst = editedDuration()
    expect(afterFirst).toBeCloseTo(7)
    // The viewport re-fits after the length change, so a second drag selects a
    // different span — its exact size doesn't matter, only that it walks back.
    dragSelect(1, 2)
    key("Delete")
    const afterSecond = editedDuration()
    expect(afterSecond).toBeLessThan(afterFirst)
    expect(opCount()).toBe(2)

    fireEvent.click(undoBtn())
    expect(editedDuration()).toBeCloseTo(afterFirst)
    fireEvent.click(undoBtn())
    expect(editedDuration()).toBeCloseTo(10) // back to the pristine original
    expect(opCount()).toBe(0)
  })

  it("a fresh edit after undo discards the redo branch", () => {
    renderEditor()
    dragSelect(2, 5)
    key("Delete") // → 7
    fireEvent.click(undoBtn()) // → 10, redo available
    expect(redoBtn()).toBeEnabled()
    dragSelect(0, 2)
    key("Delete") // new branch → 8
    expect(editedDuration()).toBeCloseTo(8)
    expect(redoBtn()).toBeDisabled() // old redo branch dropped
  })

  it("undo/redo buttons are disabled at the stack boundaries", () => {
    renderEditor()
    expect(undoBtn()).toBeDisabled() // nothing to undo yet
    expect(redoBtn()).toBeDisabled()

    dragSelect(2, 5)
    key("Delete")
    expect(undoBtn()).toBeEnabled()
    expect(redoBtn()).toBeDisabled() // at the tip

    fireEvent.click(undoBtn())
    expect(undoBtn()).toBeDisabled() // back at the origin
    expect(redoBtn()).toBeEnabled()
  })

  it("Ctrl+Z undoes and Ctrl+Shift+Z redoes", () => {
    renderEditor()
    dragSelect(2, 5)
    key("Delete")
    expect(editedDuration()).toBeCloseTo(7)
    key("z", { ctrlKey: true })
    expect(editedDuration()).toBeCloseTo(10)
    key("z", { ctrlKey: true, shiftKey: true })
    expect(editedDuration()).toBeCloseTo(7)
  })

  it("Save as new version is disabled until an edit is made", () => {
    renderEditor()
    expect(saveBtn()).toBeDisabled()
    dragSelect(2, 5)
    key("Delete")
    expect(saveBtn()).toBeEnabled()
    fireEvent.click(undoBtn()) // no edits applied again
    expect(saveBtn()).toBeDisabled()
  })

  // --- Repaint mode (US-18.5) ----------------------------------------------

  it("shows the repaint panel only while a region is selected", () => {
    renderEditor()
    expect(screen.queryByTestId("repaint-panel")).not.toBeInTheDocument()
    dragSelect(2, 5)
    expect(screen.getByTestId("repaint-panel")).toBeInTheDocument()
  })

  it("applies a completed repaint as an undoable edit", async () => {
    submitRepaint.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["child-1"] })
    // The child clip is the full crossfade-blended result; a 6s duration lets us
    // see it land in the editor's buffer (and undo back to the original 10s).
    decodeClipAudio.mockResolvedValue({ mono: new Float32Array(480), sampleRate: 80, duration: 6 })

    renderEditor()
    dragSelect(2, 5)
    const panel = screen.getByTestId("repaint-panel")
    await userEvent.type(within(panel).getByLabelText(/Instructions/), "make it jazzy")
    await userEvent.click(within(panel).getByRole("button", { name: "Regenerate" }))

    // The decoded child replaces the buffer as a recorded repaint op.
    await waitFor(() => expect(editedDuration()).toBeCloseTo(6))
    expect(opCount()).toBe(1)
    expect(submitRepaint).toHaveBeenCalledWith(
      "c1",
      expect.objectContaining({ start: "2s", end: "5s", prompt: "make it jazzy" }),
      "test-token"
    )

    // Undoable: back to the pristine original, op log cleared.
    fireEvent.click(undoBtn())
    expect(editedDuration()).toBeCloseTo(10)
    expect(opCount()).toBe(0)
  })
})
