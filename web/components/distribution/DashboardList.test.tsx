import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DashboardList } from "@/components/distribution/DashboardList"
import type { UseReleasesPoll } from "@/hooks/use-releases-poll"
import type { ReleaseSummary } from "@/lib/releases"

vi.mock("@/hooks/use-releases-poll", () => ({ useReleasesPoll: vi.fn() }))
import { useReleasesPoll } from "@/hooks/use-releases-poll"
const mockHook = useReleasesPoll as unknown as ReturnType<typeof vi.fn>

function state(overrides: Partial<UseReleasesPoll>): UseReleasesPoll {
  return {
    releases: null,
    loading: false,
    error: null,
    lastUpdated: null,
    refresh: vi.fn(),
    ...overrides,
  }
}

const rows: ReleaseSummary[] = [
  {
    id: "r1",
    clipId: "c1",
    title: "Neon Skyline",
    artist: "A",
    genre: "G",
    releaseDate: "2026-06-01",
    createdAt: "2026-06-01T00:00:00Z",
    channels: [{ channel: "soundcloud", status: "live", permalink: "https://x" }],
  },
]

afterEach(() => vi.clearAllMocks())

describe("DashboardList", () => {
  it("shows a loading state", () => {
    mockHook.mockReturnValue(state({ loading: true }))
    render(<DashboardList />)
    expect(screen.getByRole("status")).toHaveTextContent(/loading releases/i)
  })

  it("shows an error with a retry", async () => {
    const refresh = vi.fn()
    mockHook.mockReturnValue(state({ error: "nope", refresh }))
    render(<DashboardList />)
    expect(screen.getByRole("alert")).toHaveTextContent("nope")
    await userEvent.click(screen.getByRole("button", { name: /retry/i }))
    expect(refresh).toHaveBeenCalled()
  })

  it("keeps the list visible with an inline banner when a poll fails after data loaded", () => {
    // error set AND releases present = a transient poll failure, not initial.
    mockHook.mockReturnValue(state({ releases: rows, error: "blip", lastUpdated: Date.now() }))
    render(<DashboardList />)
    expect(screen.getByRole("link", { name: "Neon Skyline" })).toBeInTheDocument() // list still shown
    expect(screen.getByRole("alert")).toHaveTextContent(/showing the last known statuses/i)
  })

  it("shows an empty state when there are no releases", () => {
    mockHook.mockReturnValue(state({ releases: [] }))
    render(<DashboardList />)
    expect(screen.getByText(/no releases yet/i)).toBeInTheDocument()
  })

  it("renders a card per release with an updated timestamp", () => {
    mockHook.mockReturnValue(state({ releases: rows, lastUpdated: Date.now() }))
    render(<DashboardList />)
    expect(screen.getByRole("link", { name: "Neon Skyline" })).toBeInTheDocument()
    expect(screen.getByText(/updated/i)).toBeInTheDocument()
  })
})
