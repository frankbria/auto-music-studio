import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SelectionInfo } from "./SelectionInfo"

describe("SelectionInfo", () => {
  it("renders nothing without a selection", () => {
    const { container } = render(<SelectionInfo selection={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows start, end, and duration with millisecond precision", () => {
    render(<SelectionInfo selection={{ startSec: 8.2, endSec: 8.5 }} />)
    const info = screen.getByTestId("selection-info")
    expect(info).toHaveTextContent("Start 0:08.200")
    expect(info).toHaveTextContent("End 0:08.500")
    expect(info).toHaveTextContent("Duration 0:00.300")
  })

  it("formats minutes past 60 seconds", () => {
    render(<SelectionInfo selection={{ startSec: 65.5, endSec: 90 }} />)
    expect(screen.getByTestId("selection-info")).toHaveTextContent("Start 1:05.500")
  })
})
