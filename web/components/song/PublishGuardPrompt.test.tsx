import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { PublishGuardPrompt } from "@/components/song/PublishGuardPrompt"

describe("PublishGuardPrompt", () => {
  it("renders nothing when guard is null", () => {
    render(<PublishGuardPrompt guard={null} onClose={() => {}} />)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("lists a missing style tag", () => {
    render(
      <PublishGuardPrompt
        guard={{ missingTitle: false, missingStyleTags: true }}
        onClose={() => {}}
      />
    )
    expect(screen.getByText(/missing at least one style tag/i)).toBeInTheDocument()
    expect(screen.queryByText(/missing a title/i)).not.toBeInTheDocument()
  })

  it("lists both when title and style tags are missing", () => {
    render(
      <PublishGuardPrompt
        guard={{ missingTitle: true, missingStyleTags: true }}
        onClose={() => {}}
      />
    )
    expect(screen.getByText(/missing a title/i)).toBeInTheDocument()
    expect(screen.getByText(/missing at least one style tag/i)).toBeInTheDocument()
  })

  it("dismisses via the button", async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <PublishGuardPrompt
        guard={{ missingTitle: true, missingStyleTags: false }}
        onClose={onClose}
      />
    )
    await user.click(screen.getByRole("button", { name: /got it/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
