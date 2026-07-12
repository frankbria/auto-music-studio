import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { TimeRuler } from "./TimeRuler"

describe("TimeRuler mm:ss mode", () => {
  it("labels major ticks as mm:ss", () => {
    render(<TimeRuler pxPerSec={10} durationSec={60} displayMode="mm-ss" />)
    expect(screen.getByText("0:00")).toBeInTheDocument()
    expect(screen.getByText("0:10")).toBeInTheDocument()
    expect(screen.getByText("1:00")).toBeInTheDocument()
  })
})

describe("TimeRuler bars-beats mode", () => {
  it("labels major ticks as bar.beat at the default 120 BPM", () => {
    // 100px/sec, 120 BPM -> 2s/bar -> 200px between bars, well above the
    // 80px readability target, so ticks land on every bar.
    render(
      <TimeRuler pxPerSec={100} durationSec={6} displayMode="bars-beats" />
    )
    expect(screen.getByText("1.1")).toBeInTheDocument()
    expect(screen.getByText("2.1")).toBeInTheDocument()
    expect(screen.getByText("3.1")).toBeInTheDocument()
    expect(screen.getByText("4.1")).toBeInTheDocument()
  })
})

describe("TimeRuler sizing", () => {
  it("renders nothing when the duration collapses to zero width", () => {
    const { container } = render(
      <TimeRuler pxPerSec={10} durationSec={0} displayMode="mm-ss" />
    )
    expect(container.querySelectorAll("span").length).toBe(0)
  })

  it("sets its width to durationSec * pxPerSec", () => {
    const { container } = render(
      <TimeRuler pxPerSec={20} durationSec={30} displayMode="mm-ss" />
    )
    const ruler = container.firstElementChild as HTMLElement
    expect(ruler.style.width).toBe("600px")
  })
})
