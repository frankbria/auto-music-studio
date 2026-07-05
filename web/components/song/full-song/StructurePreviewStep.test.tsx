import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { StructurePreviewStep } from "@/components/song/full-song/StructurePreviewStep"

describe("StructurePreviewStep", () => {
  it("shows the seed clip, the planned sections, and the credit estimate", () => {
    render(
      <StructurePreviewStep
        seedTitle="Midnight Drive"
        seedDuration={30}
        onStart={vi.fn()}
      />
    )
    expect(screen.getByText("Midnight Drive")).toBeInTheDocument()
    // All seven canonical sections are listed (intro appears once, verse twice…).
    expect(screen.getAllByText("intro")).toHaveLength(1)
    expect(screen.getAllByText("verse")).toHaveLength(2)
    expect(screen.getAllByText("chorus")).toHaveLength(2)
    expect(screen.getByText(/Uses ~7 credits/)).toBeInTheDocument()
  })

  it("starts generation with the selected target duration", async () => {
    const onStart = vi.fn()
    render(
      <StructurePreviewStep
        seedTitle="Seed"
        seedDuration={30}
        onStart={onStart}
      />
    )
    await userEvent.click(
      screen.getByRole("button", { name: /start generation/i })
    )
    // Default target is 210s until the slider is moved.
    expect(onStart).toHaveBeenCalledWith(210)
  })
})
