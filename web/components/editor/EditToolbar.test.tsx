import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { EditToolbar, type EditToolbarProps } from "./EditToolbar"

function renderToolbar(overrides: Partial<EditToolbarProps> = {}) {
  const props: EditToolbarProps = {
    hasSelection: true,
    onFadeIn: vi.fn(),
    onFadeOut: vi.fn(),
    onSilence: vi.fn(),
    onNormalize: vi.fn(),
    onGainPreview: vi.fn(),
    onGainApply: vi.fn(),
    onCrossfade: vi.fn(),
    ...overrides,
  }
  render(<EditToolbar {...props} />)
  return props
}

const btn = (name: string) => screen.getByRole("button", { name })

describe("EditToolbar", () => {
  it("fires the region ops on click when a selection exists", () => {
    const p = renderToolbar()
    fireEvent.click(btn("Fade In"))
    fireEvent.click(btn("Fade Out"))
    fireEvent.click(btn("Silence"))
    fireEvent.click(btn("Normalize"))
    expect(p.onFadeIn).toHaveBeenCalledOnce()
    expect(p.onFadeOut).toHaveBeenCalledOnce()
    expect(p.onSilence).toHaveBeenCalledOnce()
    expect(p.onNormalize).toHaveBeenCalledOnce()
  })

  it("disables selection-only tools without a selection (Normalize/Crossfade stay on)", () => {
    renderToolbar({ hasSelection: false })
    expect(btn("Fade In")).toBeDisabled()
    expect(btn("Fade Out")).toBeDisabled()
    expect(btn("Silence")).toBeDisabled()
    expect(btn("Gain")).toBeDisabled()
    expect(btn("Normalize")).toBeEnabled()
    expect(btn("Crossfade")).toBeEnabled()
  })

  it("previews on open, commits on Apply, reverts on close (gain)", () => {
    const p = renderToolbar()
    fireEvent.click(btn("Gain"))
    expect(p.onGainPreview).toHaveBeenLastCalledWith(0) // live preview starts at 0 dB
    fireEvent.click(btn("Apply gain"))
    expect(p.onGainApply).toHaveBeenCalledWith(0)
    expect(p.onGainPreview).toHaveBeenLastCalledWith(null) // preview cleared on close
  })

  it("applies a crossfade at the default duration (100 ms)", () => {
    const p = renderToolbar()
    fireEvent.click(btn("Crossfade"))
    fireEvent.click(btn("Apply crossfade"))
    expect(p.onCrossfade).toHaveBeenCalledWith(0.1)
  })

  it("carries a non-default gain slider value through to Apply", () => {
    const p = renderToolbar()
    fireEvent.click(btn("Gain"))
    const slider = screen.getByRole("slider", { name: "Gain in decibels" })
    slider.focus()
    fireEvent.keyDown(slider, { key: "ArrowRight" }) // +0.5 dB step
    fireEvent.click(btn("Apply gain"))
    expect(p.onGainApply).toHaveBeenCalledWith(0.5)
  })

  it("carries a non-default crossfade slider value through to Apply", () => {
    const p = renderToolbar()
    fireEvent.click(btn("Crossfade"))
    const slider = screen.getByRole("slider", {
      name: "Crossfade duration in milliseconds",
    })
    slider.focus()
    fireEvent.keyDown(slider, { key: "ArrowRight" }) // +10 ms step → 110 ms
    fireEvent.click(btn("Apply crossfade"))
    expect(p.onCrossfade).toHaveBeenCalledWith(0.11)
  })
})
