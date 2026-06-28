import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { InputChip } from "@/components/create/InputChip"

describe("InputChip", () => {
  it("renders the label", () => {
    render(<InputChip type="audio" label="My clip" onRemove={() => {}} />)
    expect(screen.getByText("My clip")).toBeInTheDocument()
  })

  it("fires onRemove when the remove button is clicked", async () => {
    const onRemove = vi.fn()
    const user = userEvent.setup()
    render(<InputChip type="voice" label="Aria" onRemove={onRemove} />)

    await user.click(screen.getByRole("button", { name: /remove aria/i }))
    expect(onRemove).toHaveBeenCalledOnce()
  })
})
