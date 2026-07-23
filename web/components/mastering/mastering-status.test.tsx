import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  MasteringStatus,
  MasteringStatusBadge,
} from "@/components/mastering/mastering-status"

afterEach(() => vi.clearAllMocks())

describe("MasteringStatus", () => {
  it.each([
    ["submitting", /submitting/i],
    ["queued", /queued/i],
    ["processing", /processing/i],
    ["preview_ready", /preview ready/i],
    ["approved", /approved/i],
  ] as const)("shows a status for %s", (status, re) => {
    render(<MasteringStatus status={status} />)
    expect(screen.getByRole("status")).toHaveTextContent(re)
  })

  it("shows the error and a Retry button when failed", async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(<MasteringStatus status="failed" error="boom" onRetry={onRetry} />)

    expect(screen.getByRole("alert")).toHaveTextContent("boom")
    await user.click(screen.getByRole("button", { name: /retry/i }))
    expect(onRetry).toHaveBeenCalled()
  })

  it("omits Retry when no handler is given", () => {
    render(<MasteringStatus status="failed" error="boom" />)
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })
})

describe("MasteringStatusBadge", () => {
  it.each([
    ["queued", /queued/i],
    ["processing", /processing/i],
    ["preview_ready", /preview ready/i],
    ["approved", /approved/i],
    ["failed", /failed/i],
  ] as const)("labels the %s state", (status, re) => {
    render(<MasteringStatusBadge status={status} />)
    expect(screen.getByText(re)).toBeInTheDocument()
  })
})
