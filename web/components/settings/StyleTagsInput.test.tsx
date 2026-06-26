import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { StyleTagsInput } from "@/components/settings/StyleTagsInput"

describe("StyleTagsInput", () => {
  it("renders existing tags as removable pills", async () => {
    const onChange = vi.fn()
    render(<StyleTagsInput tags={["cello", "lo-fi"]} onChange={onChange} />)

    expect(screen.getByText("cello")).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Remove cello" }))
    expect(onChange).toHaveBeenCalledWith(["lo-fi"])
  })

  it("adds a tag on Enter", async () => {
    const onChange = vi.fn()
    render(<StyleTagsInput tags={[]} onChange={onChange} />)
    const user = userEvent.setup()
    const input = screen.getByLabelText("Add a style tag")
    await user.type(input, "ambient{Enter}")
    expect(onChange).toHaveBeenCalledWith(["ambient"])
  })

  it("normalizes a custom tag to lowercase", async () => {
    const onChange = vi.fn()
    render(<StyleTagsInput tags={[]} onChange={onChange} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Add a style tag"), "LoFi{Enter}")
    expect(onChange).toHaveBeenCalledWith(["lofi"])
  })

  it("rejects a duplicate tag with an inline error", async () => {
    const onChange = vi.fn()
    render(<StyleTagsInput tags={["jazz"]} onChange={onChange} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Add a style tag"), "Jazz{Enter}")
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole("alert")).toHaveTextContent(/already/i)
  })

  it("shows typeahead suggestions filtered by input", async () => {
    render(<StyleTagsInput tags={[]} onChange={vi.fn()} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Add a style tag"), "or")
    expect(
      screen.getByRole("option", { name: "orchestral" })
    ).toBeInTheDocument()
  })
})
