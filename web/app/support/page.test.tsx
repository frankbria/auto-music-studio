import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import SupportPage from "@/app/support/page"

afterEach(() => vi.unstubAllEnvs())

describe("support page (#339)", () => {
  it("links the deployment's support contact", () => {
    vi.stubEnv("SUPPORT_CONTACT", "help@example.com")
    render(<SupportPage />)

    expect(
      screen.getByRole("link", { name: "help@example.com" })
    ).toHaveAttribute("href", "mailto:help@example.com")
  })

  it("still explains how to get help when none is configured", () => {
    vi.stubEnv("SUPPORT_CONTACT", "")
    render(<SupportPage />)

    expect(
      screen.getByText(/Contact the team that runs this site/)
    ).toBeInTheDocument()
  })
})
