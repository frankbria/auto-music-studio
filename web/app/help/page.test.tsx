import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import HelpPage from "@/app/help/page"

describe("help page (#342)", () => {
  it("covers the core workflows, each section reachable from the top", () => {
    render(<HelpPage />)

    for (const title of [
      "Make a song",
      "Find, play and edit your songs",
      "Share and release",
      "Your account and plan",
    ]) {
      expect(
        screen.getByRole("heading", { level: 2, name: title })
      ).toBeInTheDocument()
      expect(screen.getByRole("link", { name: title })).toHaveAttribute(
        "href",
        expect.stringMatching(/^#/)
      )
    }
  })

  it("points at the real screens, support and the API docs", () => {
    render(<HelpPage />)

    for (const [name, href] of [
      ["Create", "/create"],
      ["Library", "/me"],
      ["Studio", "/studio"],
      ["Mastering & Distribution", "/release"],
      ["Labs", "/labs"],
    ]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href)
    }
    expect(
      screen.getByRole("link", { name: "Get help from the team" })
    ).toHaveAttribute("href", "/support")
    expect(screen.getByRole("link", { name: "/docs" })).toHaveAttribute(
      "href",
      "/docs"
    )
  })
})
