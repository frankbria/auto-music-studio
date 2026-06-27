import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SortDropdown } from "@/components/workspace/SortDropdown"

describe("SortDropdown", () => {
  it("shows the current sort label", () => {
    render(<SortDropdown value="oldest" onChange={vi.fn()} />)
    expect(screen.getByRole("button", { name: /oldest/i })).toBeInTheDocument()
  })

  it("emits the chosen sort order", async () => {
    const onChange = vi.fn()
    render(<SortDropdown value="newest" onChange={onChange} />)
    await userEvent.click(screen.getByRole("button", { name: /newest/i }))
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Oldest" }))
    expect(onChange).toHaveBeenCalledWith("oldest")
  })
})
