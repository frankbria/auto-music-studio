import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { VisibilityToggle } from "@/components/song/VisibilityToggle"

describe("VisibilityToggle", () => {
  it("shows the current state's icon and label on the trigger", () => {
    render(<VisibilityToggle value="unlisted" onChange={vi.fn()} />)
    expect(
      screen.getByRole("button", { name: "Visibility: Unlisted" })
    ).toBeInTheDocument()
  })

  it("lists all three options and marks the current one selected", async () => {
    render(<VisibilityToggle value="private" onChange={vi.fn()} />)
    await userEvent.click(
      screen.getByRole("button", { name: /visibility: private/i })
    )
    const privateItem = screen.getByRole("menuitemradio", { name: "Private" })
    expect(privateItem).toHaveAttribute("aria-checked", "true")
    expect(
      screen.getByRole("menuitemradio", { name: "Unlisted" })
    ).toHaveAttribute("aria-checked", "false")
    expect(
      screen.getByRole("menuitemradio", { name: "Public" })
    ).toHaveAttribute("aria-checked", "false")
  })

  it("calls onChange with the selected option", async () => {
    const onChange = vi.fn()
    render(<VisibilityToggle value="private" onChange={onChange} />)
    await userEvent.click(
      screen.getByRole("button", { name: /visibility: private/i })
    )
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Public" }))
    expect(onChange).toHaveBeenCalledWith("public")
  })

  it("disables the trigger when disabled", () => {
    render(<VisibilityToggle value="private" onChange={vi.fn()} disabled />)
    expect(screen.getByRole("button", { name: /visibility/i })).toBeDisabled()
  })
})
