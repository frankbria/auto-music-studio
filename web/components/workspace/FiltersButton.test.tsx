import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { FiltersButton } from "@/components/workspace/FiltersButton"
import { EMPTY_FILTERS } from "@/lib/workspace-clips"

describe("FiltersButton", () => {
  it("shows the active-filter count badge", () => {
    render(
      <FiltersButton
        filters={{ liked: true, public: false, uploads: true }}
        onFiltersChange={vi.fn()}
      />
    )
    expect(screen.getByText("2")).toBeInTheDocument()
  })

  it("omits the badge when no filters are active", () => {
    render(<FiltersButton filters={EMPTY_FILTERS} onFiltersChange={vi.fn()} />)
    expect(screen.queryByText("0")).not.toBeInTheDocument()
  })

  it("toggling a switch emits the updated filters", async () => {
    const onFiltersChange = vi.fn()
    render(
      <FiltersButton filters={EMPTY_FILTERS} onFiltersChange={onFiltersChange} />
    )
    await userEvent.click(screen.getByRole("button", { name: /filters/i }))
    await userEvent.click(screen.getByLabelText("Liked"))
    expect(onFiltersChange).toHaveBeenCalledWith({
      liked: true,
      public: false,
      uploads: false,
    })
  })
})
