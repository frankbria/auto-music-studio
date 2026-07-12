import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Playhead } from "./Playhead"

describe("Playhead", () => {
  it("positions itself from playheadSec × pxPerSec", () => {
    const { getByTestId } = render(<Playhead playheadSec={5} pxPerSec={20} />)
    expect(getByTestId("playhead").style.left).toBe("100px")
  })

  it("sits at the left edge when the playhead is at 0", () => {
    const { getByTestId } = render(<Playhead playheadSec={0} pxPerSec={20} />)
    expect(getByTestId("playhead").style.left).toBe("0px")
  })

  it("is decorative — hidden from the accessibility tree", () => {
    const { getByTestId } = render(<Playhead playheadSec={5} pxPerSec={20} />)
    expect(getByTestId("playhead")).toHaveAttribute("aria-hidden", "true")
  })
})
