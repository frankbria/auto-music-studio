import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

const notFound = vi.fn()
// The shared setup mock omits notFound; the profile 404 path needs it.
vi.mock("next/navigation", () => ({
  usePathname: () => "/@nova",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  notFound: () => notFound(),
}))

import { ProfileView } from "@/components/profile/ProfileView"
import type { PublicProfile } from "@/lib/profiles"
import { makeClip } from "@/test/clip-factory"
import { SignedIn } from "@/test/signed-in"

const NOVA: PublicProfile = {
  handle: "nova",
  display_name: "Nova Bloom",
  bio: "Synthwave and neon-lit electronic.",
  style_tags: ["synthwave", "ambient"],
  joined_at: "2026-01-14T12:00:00+00:00",
  clips: [
    makeClip({ id: "c1", title: "Neon Skyline", is_public: true }),
    makeClip({ id: "c2", title: "Pulse Theory", is_public: true }),
  ],
}

function stubProfile(...responses: Response[]) {
  const fetchMock = vi.fn()
  for (const res of responses) fetchMock.mockResolvedValueOnce(res)
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status })

afterEach(() => {
  notFound.mockReset()
  vi.unstubAllGlobals()
})

describe("ProfileView (US-20.5, #654)", () => {
  it("renders identity, bio, style tags, join date and the songs grid", async () => {
    const fetchMock = stubProfile(json(NOVA))
    render(<ProfileView handle="@nova" />)

    expect(screen.getByText(/Loading profile/)).toBeInTheDocument()
    expect(
      await screen.findByRole("heading", { name: "Nova Bloom" })
    ).toBeInTheDocument()
    expect(screen.getByText("@nova")).toBeInTheDocument()
    expect(screen.getAllByText(NOVA.bio!).length).toBeGreaterThan(0)
    for (const tag of NOVA.style_tags) {
      expect(screen.getAllByText(tag).length).toBeGreaterThan(0)
    }
    expect(screen.getAllByText("Joined January 2026").length).toBeGreaterThan(0)
    expect(screen.getAllByTestId("explore-clip-card")).toHaveLength(2)
    expect(screen.getByText("Neon Skyline")).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe("/api/discover/profiles/nova")
  })

  it("has no follow, follower counts or playlists tab", async () => {
    stubProfile(json(NOVA))
    render(
      <SignedIn>
        <ProfileView handle="@nova" />
      </SignedIn>
    )
    await screen.findByRole("heading", { name: "Nova Bloom" })
    expect(screen.queryByText(/followers/i)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /follow/i })).toBeNull()
    expect(screen.queryByRole("tab", { name: "Playlists" })).toBeNull()
    expect(screen.getByRole("tab", { name: "About" })).toBeInTheDocument()
  })

  it("falls back to @handle without a display name, and shows an empty songs state", async () => {
    stubProfile(json({ ...NOVA, display_name: null, bio: null, clips: [] }))
    render(<ProfileView handle="@nova" />)
    expect(
      await screen.findByRole("heading", { name: "@nova" })
    ).toBeInTheDocument()
    expect(screen.getByText("No published songs yet.")).toBeInTheDocument()
  })

  it("sends the signed-in viewer's token", async () => {
    const fetchMock = stubProfile(json(NOVA))
    render(
      <SignedIn>
        <ProfileView handle="@nova" />
      </SignedIn>
    )
    await screen.findByRole("heading", { name: "Nova Bloom" })
    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get("authorization")).toBe("Bearer tok")
  })

  it("404s on an unknown handle", async () => {
    stubProfile(json({ detail: "Profile not found." }, 404))
    render(<ProfileView handle="@ghost" />)
    await waitFor(() => expect(notFound).toHaveBeenCalled())
  })

  it("shows an error with a retry that reloads the profile", async () => {
    const fetchMock = stubProfile(json({}, 502), json(NOVA))
    render(<ProfileView handle="@nova" />)

    expect(
      await screen.findByText("Couldn't load this profile.")
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(
      await screen.findByRole("heading", { name: "Nova Bloom" })
    ).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(notFound).not.toHaveBeenCalled()
  })
})
