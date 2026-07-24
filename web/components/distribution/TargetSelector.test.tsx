import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import { TargetSelector } from "@/components/distribution/TargetSelector"
import type { Clip } from "@/lib/workspace-clips"

// SoundCloudCard fetches status on mount; mock useAuth + the SoundCloud calls so
// the selector renders without an AuthProvider or real network.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: "tok" }) }))
vi.mock("@/lib/distribution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/distribution")>()
  return {
    ...actual,
    getSoundCloudStatus: vi.fn(async () => ({
      kind: "ok",
      status: { connected: false, username: null, connectedAt: null, tokenValid: null },
    })),
  }
})

function clip(): Clip {
  return {
    id: "clip-1",
    workspace_id: null,
    title: "Nightfall",
    bpm: 124,
    key: "Am",
    style_tags: ["House"],
  } as Clip
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe("TargetSelector", () => {
  it("renders all three distribution targets with a kind badge each", () => {
    render(<TargetSelector clip={clip()} />)
    expect(screen.getByText("SoundCloud")).toBeInTheDocument()
    expect(screen.getByText("LANDR")).toBeInTheDocument()
    expect(screen.getByText("DistroKid")).toBeInTheDocument()
    expect(screen.getByText("Automated")).toBeInTheDocument()
    expect(screen.getAllByText("Guided")).toHaveLength(2)
  })

  it("shows a Requirements disclosure for every target", () => {
    render(<TargetSelector clip={clip()} />)
    expect(screen.getAllByText("Requirements")).toHaveLength(3)
  })

  it("enables the guided Prepare buttons when a song is selected", () => {
    render(<TargetSelector clip={clip()} />)
    const prepare = screen.getAllByRole("button", { name: /prepare package/i })
    expect(prepare).toHaveLength(2)
    prepare.forEach((btn) => expect(btn).toBeEnabled())
  })

  it("disables guided actions when no song is selected", () => {
    render(<TargetSelector clip={null} />)
    screen
      .getAllByRole("button", { name: /prepare package/i })
      .forEach((btn) => expect(btn).toBeDisabled())
  })
})
