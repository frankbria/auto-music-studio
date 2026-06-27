import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { WorkspaceBreadcrumb } from "@/components/workspace/WorkspaceBreadcrumb"
import type { Workspace } from "@/lib/workspace-clips"

const workspace: Workspace = {
  id: "w1",
  name: "My Beats",
  clip_count: 3,
  is_default: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
}

describe("WorkspaceBreadcrumb", () => {
  it("shows the current workspace name", () => {
    render(<WorkspaceBreadcrumb workspace={workspace} />)
    expect(screen.getByText("My Beats")).toBeInTheDocument()
  })

  it("renders a placeholder when no workspace is set", () => {
    render(<WorkspaceBreadcrumb workspace={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("fires onNavigate when the root segment is clicked", async () => {
    const onNavigate = vi.fn()
    render(<WorkspaceBreadcrumb workspace={workspace} onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole("button", { name: /workspaces/i }))
    expect(onNavigate).toHaveBeenCalledOnce()
  })
})
