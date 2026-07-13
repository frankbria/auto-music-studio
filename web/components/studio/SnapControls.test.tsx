import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { SnapControls } from "./SnapControls"
import { StudioProvider } from "@/contexts/studio-context"

function Harness() {
  return (
    <StudioProvider>
      <SnapControls />
    </StudioProvider>
  )
}

describe("SnapControls (US-19.3)", () => {
  it("renders the snap toggle pressed by default and toggles it", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const toggle = screen.getByRole("button", { name: "Snap to grid" })
    expect(toggle).toHaveAttribute("aria-pressed", "true")
    await user.click(toggle)
    expect(toggle).toHaveAttribute("aria-pressed", "false")
    await user.click(toggle)
    expect(toggle).toHaveAttribute("aria-pressed", "true")
  })

  it("offers all four grid resolutions and selects one", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole("button", { name: "Snap resolution" })
    expect(trigger).toHaveTextContent("1 beat")

    await user.click(trigger)
    for (const label of ["1 bar", "1 beat", "1/2 beat", "1/4 beat"]) {
      expect(screen.getByRole("menuitem", { name: label })).toBeInTheDocument()
    }
    await user.click(screen.getByRole("menuitem", { name: "1 bar" }))
    expect(trigger).toHaveTextContent("1 bar")
  })
})
