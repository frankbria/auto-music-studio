import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { VisibilityBadge } from "@/components/song/VisibilityBadge"

describe("VisibilityBadge", () => {
  it("labels each visibility state", () => {
    const { rerender } = render(<VisibilityBadge visibility="private" />)
    expect(screen.getByText("Private")).toBeInTheDocument()

    rerender(<VisibilityBadge visibility="unlisted" />)
    expect(screen.getByText("Unlisted")).toBeInTheDocument()

    rerender(<VisibilityBadge visibility="public" />)
    expect(screen.getByText("Public")).toBeInTheDocument()
  })
})
