import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { PaginationControls } from "@/components/workspace/PaginationControls"

describe("PaginationControls", () => {
  it("shows the page indicator", () => {
    render(<PaginationControls page={2} totalPages={5} onPageChange={vi.fn()} />)
    expect(screen.getByText("Page 2 of 5")).toBeInTheDocument()
  })

  it("disables Prev on the first page and Next on the last", () => {
    const { rerender } = render(
      <PaginationControls page={1} totalPages={3} onPageChange={vi.fn()} />
    )
    expect(screen.getByLabelText("Previous page")).toBeDisabled()
    expect(screen.getByLabelText("Next page")).toBeEnabled()

    rerender(<PaginationControls page={3} totalPages={3} onPageChange={vi.fn()} />)
    expect(screen.getByLabelText("Next page")).toBeDisabled()
  })

  it("requests the next/previous page on click", async () => {
    const onPageChange = vi.fn()
    render(<PaginationControls page={2} totalPages={5} onPageChange={onPageChange} />)
    await userEvent.click(screen.getByLabelText("Next page"))
    expect(onPageChange).toHaveBeenCalledWith(3)
    await userEvent.click(screen.getByLabelText("Previous page"))
    expect(onPageChange).toHaveBeenCalledWith(1)
  })
})
