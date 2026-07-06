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
})
