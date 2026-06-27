import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { GenerationProgress } from "@/components/create/GenerationProgress"

describe("GenerationProgress", () => {
  it("shows the model name and time estimate", () => {
    render(<GenerationProgress estimatedSeconds={30} modelName="Turbo" />)
    const status = screen.getByRole("status")
    expect(status).toHaveTextContent(/Turbo/)
    expect(status).toHaveTextContent(/~30s/)
  })

  it("omits the estimate when zero", () => {
    render(<GenerationProgress estimatedSeconds={0} modelName="Base" />)
    expect(screen.getByRole("status")).not.toHaveTextContent(/~/)
  })

  it("renders per-step progress when provided", () => {
    render(<GenerationProgress estimatedSeconds={10} progress="step 2 of 5" />)
    expect(screen.getByRole("status")).toHaveTextContent("step 2 of 5")
  })
})
