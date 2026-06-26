import { useState } from "react"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { InspirationTags } from "@/components/create/InspirationTags"

// Controlled component — drive it through a stateful harness so clicks that call
// onChange are reflected back, matching real usage in the form.
function Harness() {
  const [tags, setTags] = useState<string[]>([])
  return <InspirationTags selectedTags={tags} onChange={setTags} />
}

afterEach(() => vi.restoreAllMocks())

describe("InspirationTags", () => {
  it("renders suggestion pills and shows one as selected on click", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const suggestionRow = screen
      .getByRole("button", { name: "Shuffle suggestions" })
      .closest("div") as HTMLElement
    const firstTag = within(suggestionRow).getAllByRole("button")[0]
    const label = firstTag.textContent ?? ""
    await user.click(firstTag)

    // The selected tag now appears in the "Selected tags" group as a chip.
    const selected = screen.getByLabelText("Selected tags")
    expect(within(selected).getByText(label)).toBeInTheDocument()
  })

  it("removes a selected tag when its chip is dismissed", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const suggestionRow = screen
      .getByRole("button", { name: "Shuffle suggestions" })
      .closest("div") as HTMLElement
    const firstTag = within(suggestionRow).getAllByRole("button")[0]
    const label = firstTag.textContent ?? ""
    await user.click(firstTag)

    await user.click(screen.getByRole("button", { name: `Remove ${label}` }))
    expect(screen.queryByLabelText("Selected tags")).not.toBeInTheDocument()
  })

  it("replaces displayed suggestions on shuffle", async () => {
    // Deterministic shuffle: first render uses the unstubbed order; after the
    // stub, picks rotate predictably so the set changes.
    const user = userEvent.setup()
    render(<Harness />)

    const before = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      .filter((t) => t && t !== "")
      .join("|")

    vi.spyOn(Math, "random").mockReturnValue(0.99)
    await user.click(screen.getByRole("button", { name: "Shuffle suggestions" }))

    const after = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      .filter((t) => t && t !== "")
      .join("|")

    expect(after).not.toBe(before)
  })

  it("keeps selected tags visible through a shuffle", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const suggestionRow = screen
      .getByRole("button", { name: "Shuffle suggestions" })
      .closest("div") as HTMLElement
    const firstTag = within(suggestionRow).getAllByRole("button")[0]
    const label = firstTag.textContent ?? ""
    await user.click(firstTag)

    await user.click(screen.getByRole("button", { name: "Shuffle suggestions" }))

    const selected = screen.getByLabelText("Selected tags")
    expect(within(selected).getByText(label)).toBeInTheDocument()
  })
})
