import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { WaveformCanvas } from "./WaveformCanvas"
import type { ClipAudio } from "@/lib/audio-peaks"
import type { Viewport } from "@/lib/waveform-viewport"

// Direct coverage for the canvas's pointer/wheel input translation — the most
// stateful code in the editor. jsdom's getBoundingClientRect returns {left:0},
// so clientX maps 1:1 to the in-canvas x used by the seek/pan/zoom math.

const audio: ClipAudio = { mono: new Float32Array(8000), sampleRate: 8000, duration: 10 }
const viewport: Viewport = { pxPerSec: 80, scrollSec: 5 } // zoomed in, mid-clip

function setup() {
  const onSeek = vi.fn()
  const onZoom = vi.fn()
  const onScrollSec = vi.fn()
  const onSelect = vi.fn()
  render(
    <WaveformCanvas
      audio={audio}
      viewport={viewport}
      width={800}
      height={160}
      playheadSec={5}
      onSeek={onSeek}
      onZoom={onZoom}
      onScrollSec={onScrollSec}
      onSelect={onSelect}
    />
  )
  return {
    canvas: screen.getByRole("img", { name: "Waveform" }),
    onSeek,
    onZoom,
    onScrollSec,
    onSelect,
  }
}

describe("WaveformCanvas input", () => {
  it("seeks on a tap with no movement", () => {
    const { canvas, onSeek, onSelect } = setup()
    fireEvent.pointerDown(canvas, { clientX: 240, pointerId: 1 })
    fireEvent.pointerUp(canvas, { clientX: 240, pointerId: 1 })
    // xToSec(240) = scrollSec 5 + 240/80 = 8s.
    expect(onSeek).toHaveBeenCalledWith(8)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it("selects (not seeks) when the pointer drags past the threshold", () => {
    const { canvas, onSeek, onSelect } = setup()
    fireEvent.pointerDown(canvas, { clientX: 400, pointerId: 1 })
    fireEvent.pointerMove(canvas, { clientX: 480, pointerId: 1 }) // dragged +80px
    fireEvent.pointerUp(canvas, { clientX: 480, pointerId: 1 })
    // start xToSec(400) = 5 + 400/80 = 10s; end xToSec(480) = 5 + 480/80 = 11s.
    expect(onSelect).toHaveBeenLastCalledWith(10, 11)
    expect(onSeek).not.toHaveBeenCalled()
  })

  it("zooms on a two-finger pinch", () => {
    const { canvas, onZoom } = setup()
    fireEvent.pointerDown(canvas, { clientX: 100, pointerId: 1 })
    fireEvent.pointerDown(canvas, { clientX: 200, pointerId: 2 })
    fireEvent.pointerMove(canvas, { clientX: 300, pointerId: 2 }) // dist 200, primes
    fireEvent.pointerMove(canvas, { clientX: 400, pointerId: 2 }) // dist 300 → 1.5x
    expect(onZoom).toHaveBeenCalled()
    const [nextPx] = onZoom.mock.calls.at(-1)!
    expect(nextPx).toBeCloseTo(80 * 1.5) // pxPerSec * (300/200)
  })

  it("zooms on Ctrl+wheel and scrolls on a plain wheel", () => {
    const { canvas, onZoom, onScrollSec } = setup()
    fireEvent.wheel(canvas, { deltaY: -100, ctrlKey: true, clientX: 400 })
    expect(onZoom).toHaveBeenCalled()
    fireEvent.wheel(canvas, { deltaY: 40, clientX: 400 })
    expect(onScrollSec).toHaveBeenCalled()
  })
})
