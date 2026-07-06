import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { SelectionOverlay } from "./SelectionOverlay"
import type { Viewport } from "@/lib/waveform-viewport"

// jsdom's getBoundingClientRect returns {left:0}, so clientX maps 1:1 to the
// in-overlay x used for the time conversion.
const viewport: Viewport = { pxPerSec: 80, scrollSec: 0 }

function setup(selection: { startSec: number; endSec: number } | null) {
  const onAdjust = vi.fn()
  render(
    <SelectionOverlay
      selection={selection}
      viewport={viewport}
      width={800}
      height={160}
      duration={10}
      onAdjust={onAdjust}
    />
  )
  return { onAdjust }
}

describe("SelectionOverlay", () => {
  it("renders nothing without a selection", () => {
    setup(null)
    expect(screen.queryByTestId("selection-overlay")).not.toBeInTheDocument()
  })

  it("positions the highlight from start to end (px = sec * pxPerSec)", () => {
    setup({ startSec: 2, endSec: 5 })
    const overlay = screen.getByTestId("selection-overlay")
    const rect = overlay.firstElementChild as HTMLElement
    expect(rect.style.left).toBe("160px") // 2s * 80
    expect(rect.style.width).toBe("240px") // (5-2)s * 80
  })

  it("reports the dragged edge as a time under the pointer", () => {
    const { onAdjust } = setup({ startSec: 2, endSec: 5 })
    const startHandle = screen.getByRole("slider", { name: "Selection start handle" })
    fireEvent.pointerDown(startHandle, { clientX: 160, pointerId: 1 })
    fireEvent.pointerMove(startHandle, { clientX: 240, pointerId: 1 })
    // xToSec(240) = 0 + 240/80 = 3s.
    expect(onAdjust).toHaveBeenCalledWith("start", 3)
  })

  it("nudges an edge by a fine step with Arrow keys", () => {
    const { onAdjust } = setup({ startSec: 2, endSec: 5 })
    const startHandle = screen.getByRole("slider", { name: "Selection start handle" })
    fireEvent.keyDown(startHandle, { key: "ArrowRight" })
    expect(onAdjust).toHaveBeenLastCalledWith("start", expect.closeTo(2.05))
    fireEvent.keyDown(startHandle, { key: "ArrowLeft" })
    expect(onAdjust).toHaveBeenLastCalledWith("start", expect.closeTo(1.95))
  })

  it("keeps both handles mounted when an edge scrolls out of view", () => {
    const onAdjust = vi.fn()
    render(
      <SelectionOverlay
        selection={{ startSec: 2, endSec: 5 }}
        viewport={{ pxPerSec: 80, scrollSec: 3 }} // start at x = -80 (off-left)
        width={800}
        height={160}
        duration={10}
        onAdjust={onAdjust}
      />
    )
    // The start handle must stay mounted so an in-progress drag keeps its
    // pointer capture instead of freezing at the edge.
    expect(
      screen.getByRole("slider", { name: "Selection start handle" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("slider", { name: "Selection end handle" })
    ).toBeInTheDocument()
  })
})
