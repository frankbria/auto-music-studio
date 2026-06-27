import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"

describe("ClipSearchInput", () => {
  it("reflects the controlled value and emits changes", async () => {
    const onChange = vi.fn()
    render(<ClipSearchInput value="" onChange={onChange} />)
    await userEvent.type(screen.getByLabelText("Search clips"), "a")
    expect(onChange).toHaveBeenCalledWith("a")
  })

  it("shows a clear button only when there is a value, and clears on click", async () => {
    const onChange = vi.fn()
    const { rerender } = render(<ClipSearchInput value="" onChange={onChange} />)
    expect(screen.queryByLabelText("Clear search")).not.toBeInTheDocument()

    rerender(<ClipSearchInput value="lofi" onChange={onChange} />)
    await userEvent.click(screen.getByLabelText("Clear search"))
    expect(onChange).toHaveBeenCalledWith("")
  })
})
