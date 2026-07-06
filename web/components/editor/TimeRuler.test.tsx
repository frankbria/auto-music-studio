import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { TimeRuler } from "./TimeRuler"

describe("TimeRuler", () => {
  it("labels major ticks as mm:ss for the current viewport", () => {
    // 60s clip at fit zoom (10px/sec in 600px) → 10s ticks.
    render(
      <TimeRuler
        viewport={{ pxPerSec: 10, scrollSec: 0 }}
        width={600}
        duration={60}
      />
    )
    expect(screen.getByText("0:00")).toBeInTheDocument()
    expect(screen.getByText("0:10")).toBeInTheDocument()
    expect(screen.getByText("1:00")).toBeInTheDocument()
  })

  it("shows finer, consecutive-second labels when zoomed in", () => {
    // 200px/sec → 0.5s ticks, so a 600px window shows 0–3s with consecutive
    // whole-second labels — impossible at the coarse fit zoom (10s jumps).
    render(
      <TimeRuler
        viewport={{ pxPerSec: 200, scrollSec: 0 }}
        width={600}
        duration={60}
      />
    )
    expect(screen.getAllByText("0:01").length).toBeGreaterThan(0)
    expect(screen.getAllByText("0:02").length).toBeGreaterThan(0)
    expect(screen.getAllByText("0:03").length).toBeGreaterThan(0)
  })

  it("renders nothing before the width is measured", () => {
    const { container } = render(
      <TimeRuler
        viewport={{ pxPerSec: 10, scrollSec: 0 }}
        width={0}
        duration={60}
      />
    )
    expect(container.querySelectorAll("span").length).toBe(0)
  })
})
