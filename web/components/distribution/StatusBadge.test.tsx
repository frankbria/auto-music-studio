import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatusBadge } from "@/components/distribution/StatusBadge"

describe("StatusBadge", () => {
  it.each([
    ["draft", /draft/i],
    ["ready", /ready/i],
    ["submitted", /submitted/i],
    ["in_review", /in review/i],
    ["live", /live/i],
    ["rejected", /rejected/i],
  ] as const)("labels the %s state", (status, re) => {
    render(<StatusBadge status={status} />)
    expect(screen.getByText(re)).toBeInTheDocument()
  })

  it("prefixes the channel name when given", () => {
    render(<StatusBadge status="live" channel="soundcloud" />)
    expect(screen.getByText(/SoundCloud · Live/)).toBeInTheDocument()
  })
})
