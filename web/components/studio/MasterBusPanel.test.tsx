import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { act, useRef } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MasterBusPanel } from "./MasterBusPanel"
import { StudioProvider, useStudio } from "@/contexts/studio-context"
import { DEFAULT_MASTER_BUS } from "@/lib/master-bus"

function stubRaf() {
  let nextId = 1
  const callbacks = new Map<number, FrameRequestCallback>()
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((cb: FrameRequestCallback) => {
      const id = nextId++
      callbacks.set(id, cb)
      return id
    })
  )
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => {
      callbacks.delete(id)
    })
  )
  return {
    tick(t: number) {
      const due = [...callbacks.entries()]
      callbacks.clear()
      for (const [, cb] of due) cb(t)
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** A null-analyser / null-limiter panel is the common case in these tests —
 * the panel must render fine before playback ever starts (US-19.5). */
function Harness({
  limiter = { current: null },
}: {
  limiter?: { current: DynamicsCompressorNode | null }
}) {
  return (
    <StudioProvider>
      <Seed limiter={limiter} />
    </StudioProvider>
  )
}

function Seed({
  limiter,
}: {
  limiter: { current: DynamicsCompressorNode | null }
}) {
  const { state } = useStudio()
  const analyserLeft = useRef<AnalyserNode | null>(null)
  const analyserRight = useRef<AnalyserNode | null>(null)
  return (
    <>
      <MasterBusPanel
        analyserLeft={analyserLeft}
        analyserRight={analyserRight}
        limiter={limiter}
      />
      <div data-testid="master-bus-probe">{JSON.stringify(state.masterBus)}</div>
    </>
  )
}

function probe() {
  return JSON.parse(screen.getByTestId("master-bus-probe").textContent!)
}

describe("MasterBusPanel rendering", () => {
  it("renders the stereo meter", () => {
    stubRaf()
    render(<Harness />)
    expect(screen.getByRole("meter", { name: "L channel level" })).toBeInTheDocument()
    expect(screen.getByRole("meter", { name: "R channel level" })).toBeInTheDocument()
  })

  it("renders every fader at its default value and range", () => {
    stubRaf()
    render(<Harness />)

    const volume = screen.getByRole("slider", { name: "Master volume" })
    expect(volume).toHaveAttribute("aria-valuenow", "0")
    expect(volume).toHaveAttribute("aria-valuemin", "-60")
    expect(volume).toHaveAttribute("aria-valuemax", "6")

    const lowFreq = screen.getByRole("slider", { name: "Low shelf frequency" })
    expect(lowFreq).toHaveAttribute(
      "aria-valuenow",
      String(DEFAULT_MASTER_BUS.eq.lowShelf.freqHz)
    )
    const midQ = screen.getByRole("slider", { name: "Mid Q" })
    expect(midQ).toHaveAttribute("aria-valuenow", String(DEFAULT_MASTER_BUS.eq.midPeak.q))
    const threshold = screen.getByRole("slider", { name: "Threshold" })
    expect(threshold).toHaveAttribute(
      "aria-valuenow",
      String(DEFAULT_MASTER_BUS.compressor.thresholdDb)
    )
    const ceiling = screen.getByRole("slider", { name: "Ceiling" })
    expect(ceiling).toHaveAttribute(
      "aria-valuenow",
      String(DEFAULT_MASTER_BUS.limiterCeilingDb)
    )
  })
})

describe("MasterBusPanel dispatch (US-19.5)", () => {
  it("changes master volume from the fader keyboard", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)
    const fader = screen.getByRole("slider", { name: "Master volume" })
    fader.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().masterVolumeDb).toBe(1)
  })

  it("changes the low shelf frequency and gain independently", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)

    const freq = screen.getByRole("slider", { name: "Low shelf frequency" })
    freq.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.lowShelf.freqHz).toBe(
      DEFAULT_MASTER_BUS.eq.lowShelf.freqHz + 5
    )
    // Untouched sibling field on the same band stays at its default.
    expect(probe().eq.lowShelf.gainDb).toBe(DEFAULT_MASTER_BUS.eq.lowShelf.gainDb)

    const gain = screen.getByRole("slider", { name: "Low shelf gain" })
    gain.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.lowShelf.gainDb).toBe(1)
  })

  it("changes the mid band's frequency, gain, and Q", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)

    const freq = screen.getByRole("slider", { name: "Mid frequency" })
    freq.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.midPeak.freqHz).toBe(
      DEFAULT_MASTER_BUS.eq.midPeak.freqHz + 10
    )

    const gain = screen.getByRole("slider", { name: "Mid gain" })
    gain.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.midPeak.gainDb).toBe(1)

    const q = screen.getByRole("slider", { name: "Mid Q" })
    q.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.midPeak.q).toBeCloseTo(DEFAULT_MASTER_BUS.eq.midPeak.q + 0.1)
  })

  it("changes the high shelf frequency and gain", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)

    const freq = screen.getByRole("slider", { name: "High shelf frequency" })
    freq.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().eq.highShelf.freqHz).toBe(
      DEFAULT_MASTER_BUS.eq.highShelf.freqHz + 50
    )
  })

  it("changes compressor threshold, ratio, attack, and release", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)

    const threshold = screen.getByRole("slider", { name: "Threshold" })
    threshold.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().compressor.thresholdDb).toBe(
      DEFAULT_MASTER_BUS.compressor.thresholdDb + 1
    )

    const ratio = screen.getByRole("slider", { name: "Ratio" })
    ratio.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().compressor.ratio).toBe(DEFAULT_MASTER_BUS.compressor.ratio + 1)

    const attack = screen.getByRole("slider", { name: "Attack" })
    attack.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().compressor.attackSec).toBeCloseTo(
      DEFAULT_MASTER_BUS.compressor.attackSec + 0.001
    )

    const release = screen.getByRole("slider", { name: "Release" })
    release.focus()
    await user.keyboard("{ArrowUp}")
    expect(probe().compressor.releaseSec).toBeCloseTo(
      DEFAULT_MASTER_BUS.compressor.releaseSec + 0.01
    )
  })

  it("changes the limiter ceiling", async () => {
    stubRaf()
    const user = userEvent.setup()
    render(<Harness />)

    const ceiling = screen.getByRole("slider", { name: "Ceiling" })
    ceiling.focus()
    await user.keyboard("{ArrowDown}")
    expect(probe().limiterCeilingDb).toBeCloseTo(
      DEFAULT_MASTER_BUS.limiterCeilingDb - 0.1
    )
  })
})

describe("MasterBusPanel limiter-active indicator (US-19.5)", () => {
  it("reads inactive when the limiter node is absent (playback hasn't started)", () => {
    stubRaf()
    render(<Harness />)
    expect(screen.getByTestId("limiter-active-indicator")).toHaveAttribute(
      "data-active",
      "false"
    )
  })

  it("goes active once the live limiter node reports gain reduction", () => {
    const raf = stubRaf()
    const limiter = { current: { reduction: -6 } as DynamicsCompressorNode }
    render(<Harness limiter={limiter} />)
    expect(screen.getByTestId("limiter-active-indicator")).toHaveAttribute(
      "data-active",
      "false"
    )

    act(() => raf.tick(16))
    expect(screen.getByTestId("limiter-active-indicator")).toHaveAttribute(
      "data-active",
      "true"
    )
  })

  it("goes back to inactive once gain reduction returns to zero", () => {
    const raf = stubRaf()
    const limiter = { current: { reduction: -6 } as DynamicsCompressorNode }
    render(<Harness limiter={limiter} />)
    act(() => raf.tick(16))
    expect(screen.getByTestId("limiter-active-indicator")).toHaveAttribute(
      "data-active",
      "true"
    )

    limiter.current = { reduction: 0 } as DynamicsCompressorNode
    act(() => raf.tick(32))
    expect(screen.getByTestId("limiter-active-indicator")).toHaveAttribute(
      "data-active",
      "false"
    )
  })
})
