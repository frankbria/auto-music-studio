import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { GenerationError } from "@/components/create/GenerationError"

describe("GenerationError", () => {
  it("shows the message and wires Retry / Dismiss", async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const onDismiss = vi.fn()
    render(
      <GenerationError
        message="Not enough credits."
        onRetry={onRetry}
        onDismiss={onDismiss}
      />
    )

    expect(screen.getByRole("alert")).toHaveTextContent("Not enough credits.")
    await user.click(screen.getByRole("button", { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledOnce()
    await user.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(onDismiss).toHaveBeenCalledOnce()
  })
})
