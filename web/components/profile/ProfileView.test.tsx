import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND")
})
// The shared setup mock omits notFound; the profile 404 path needs it.
vi.mock("next/navigation", () => ({
  usePathname: () => "/@nova",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  notFound: () => notFound(),
}))

const authState = { isAuthenticated: true }
vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => authState,
}))

import { ProfileView } from "@/components/profile/ProfileView"
import { getProfileByHandle, profileClips } from "@/lib/profiles"

afterEach(() => {
  authState.isAuthenticated = true
})

describe("ProfileView (US-20.5)", () => {
  it("renders identity, bio, and style pills (AC1, AC4)", () => {
    render(<ProfileView handle="@nova" />)
    expect(
      screen.getByRole("heading", { name: "Nova Bloom" })
    ).toBeInTheDocument()
    expect(screen.getByText("@nova")).toBeInTheDocument()
    // Style tags render as badges.
    for (const tag of getProfileByHandle("nova")!.style_tags) {
      expect(screen.getAllByText(tag).length).toBeGreaterThan(0)
    }
  })

  it("renders the published songs grid (AC2)", () => {
    render(<ProfileView handle="@nova" />)
    const expected = profileClips(getProfileByHandle("nova")!)
    expect(screen.getAllByTestId("explore-clip-card")).toHaveLength(
      expected.length
    )
    expect(screen.getByText(expected[0].title!)).toBeInTheDocument()
  })

  it("toggles follow state and moves the follower count by one (AC3)", async () => {
    const user = userEvent.setup()
    render(<ProfileView handle="@nova" />)
    const base = getProfileByHandle("nova")!.follower_count

    const btn = screen.getByTestId("follow-button")
    const count = screen.getByTestId("follower-count")
    expect(btn).toHaveTextContent("Follow")
    expect(count).toHaveAttribute("title", base.toLocaleString("en"))

    await user.click(btn)
    expect(btn).toHaveTextContent("Following")
    expect(btn).toHaveAttribute("aria-pressed", "true")
    expect(count).toHaveAttribute("title", (base + 1).toLocaleString("en"))

    await user.click(btn)
    expect(btn).toHaveTextContent("Follow")
    expect(btn).toHaveAttribute("aria-pressed", "false")
    expect(count).toHaveAttribute("title", base.toLocaleString("en"))
  })

  it("hides the follow button for anonymous viewers", () => {
    authState.isAuthenticated = false
    render(<ProfileView handle="@nova" />)
    expect(screen.queryByTestId("follow-button")).not.toBeInTheDocument()
  })

  it("shows public playlists on the Playlists tab (AC5)", async () => {
    const user = userEvent.setup()
    render(<ProfileView handle="@nova" />)
    await user.click(screen.getByRole("tab", { name: "Playlists" }))
    // Public seed playlists ("Late Night Drive", "Summer Anthems") link out.
    expect(screen.getByText("Late Night Drive")).toBeInTheDocument()
    expect(screen.getByText("Summer Anthems")).toBeInTheDocument()
    // The private "Deep Focus" seed must not leak.
    expect(screen.queryByText("Deep Focus")).not.toBeInTheDocument()
  })

  it("404s on an unknown handle", () => {
    expect(() => render(<ProfileView handle="@nobody" />)).toThrow(
      "NEXT_NOT_FOUND"
    )
    expect(notFound).toHaveBeenCalled()
  })
})
