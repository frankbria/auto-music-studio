import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Playhead } from "./Playhead"
import { TRACK_STRIP_PX } from "@/lib/timeline"

describe("Playhead", () => {
  it("positions itself from TRACK_STRIP_PX + playheadSec × pxPerSec", () => {
    // The playhead is a sibling overlay of the ruler+lanes, which are offset
    // by the track control strip — so its x must include that offset too, or
    // it lands under the strip instead of over the timeline it marks.
    const { getByTestId } = render(<Playhead playheadSec={5} pxPerSec={20} />)
    expect(getByTestId("playhead").style.left).toBe(`${TRACK_STRIP_PX + 100}px`)
  })

  it("sits at the strip's right edge when the playhead is at 0", () => {
    const { getByTestId } = render(<Playhead playheadSec={0} pxPerSec={20} />)
    expect(getByTestId("playhead").style.left).toBe(`${TRACK_STRIP_PX}px`)
  })

  it("is decorative — hidden from the accessibility tree", () => {
    const { getByTestId } = render(<Playhead playheadSec={5} pxPerSec={20} />)
    expect(getByTestId("playhead")).toHaveAttribute("aria-hidden", "true")
  })
})
