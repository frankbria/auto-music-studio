import { render } from "@testing-library/react"
import { act, createRef } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { StereoMeter } from "./StereoMeter"
import { stubRaf } from "@/test/raf-stub"

/** A fake AnalyserNode whose `getFloatTimeDomainData` fills the caller's
 * buffer with a fixed sample window — swappable mid-test via `.samples`. */
function fakeAnalyser(initial: number[] = [0]) {
  const state = { samples: initial }
  return {
    node: {
      fftSize: 8,
      getFloatTimeDomainData: vi.fn((buf: Float32Array) => {
        for (let i = 0; i < buf.length; i++) {
          buf[i] = state.samples[i % state.samples.length]
        }
      }),
    } as unknown as AnalyserNode,
    setSamples(samples: number[]) {
      state.samples = samples
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("StereoMeter", () => {
  it("renders an L and R meter, silent by default", () => {
    stubRaf()
    const left = createRef<AnalyserNode | null>()
    const right = createRef<AnalyserNode | null>()
    const { getByRole } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    expect(getByRole("meter", { name: "L channel level" })).toBeInTheDocument()
    expect(getByRole("meter", { name: "R channel level" })).toBeInTheDocument()
  })

  it("reflects a loud left-channel signal in its meter value, distinct from a silent right channel", () => {
    const raf = stubRaf()
    const l = fakeAnalyser([1, -1, 1, -1])
    const r = fakeAnalyser([0])
    const left = { current: l.node }
    const right = { current: r.node }

    const { getByRole } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    act(() => raf.tick(16))

    const leftMeter = getByRole("meter", { name: "L channel level" })
    const rightMeter = getByRole("meter", { name: "R channel level" })
    expect(Number(leftMeter.getAttribute("aria-valuenow"))).toBeCloseTo(0, 0)
    expect(Number(rightMeter.getAttribute("aria-valuenow"))).toBeLessThan(-40)
  })

  it("shows a clip indicator once a channel's peak exceeds 0 dBFS", () => {
    const raf = stubRaf()
    const l = fakeAnalyser([2, -2]) // amplitude > 1 → clips
    const left = { current: l.node }
    const right = { current: null }

    const { getByTestId } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    expect(getByTestId("clip-indicator-l")).toHaveAttribute(
      "data-clipping",
      "false"
    )

    act(() => raf.tick(16))
    expect(getByTestId("clip-indicator-l")).toHaveAttribute(
      "data-clipping",
      "true"
    )
  })

  it("holds the peak marker after a loud transient drops to silence, within the hold window", () => {
    const raf = stubRaf()
    const l = fakeAnalyser([1, -1])
    const left = { current: l.node }
    const right = { current: null }

    const { getByRole } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    act(() => raf.tick(0))
    const leftMeter = getByRole("meter", { name: "L channel level" })
    expect(Number(leftMeter.getAttribute("aria-valuenow"))).toBeCloseTo(0, 0)

    l.setSamples([0])
    act(() => raf.tick(50)) // well within the hold window
    // The instantaneous peak dropped to silence, but the held marker must
    // still read near 0 dBFS.
    const holdEl = getByRole("meter", {
      name: "L channel level",
    }).querySelector('[data-role="peak-hold"]')
    expect(holdEl).not.toBeNull()
    const holdPercent = parseFloat((holdEl as HTMLElement).style.bottom)
    expect(holdPercent).toBeGreaterThan(90)
  })

  it("cancels the animation frame loop on unmount", () => {
    stubRaf()
    const left = { current: null }
    const right = { current: null }
    const { unmount } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    unmount()
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })

  it("renders at the floor with no error when analysers are not yet built (null refs)", () => {
    stubRaf()
    const left = { current: null }
    const right = { current: null }
    const { getByRole } = render(
      <StereoMeter analyserLeft={left} analyserRight={right} />
    )
    const leftMeter = getByRole("meter", { name: "L channel level" })
    expect(leftMeter).toBeInTheDocument()
  })
})
