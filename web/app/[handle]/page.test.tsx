import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

const { paramsRef } = vi.hoisted(() => ({
  paramsRef: { current: { handle: "" } as { handle: string } | null },
}))

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND")
})
// The shared setup mock provides neither useParams nor notFound, both of which
// this shim uses to route /@handle and reject non-profile top-level paths.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => paramsRef.current,
  notFound: () => notFound(),
}))

// Stub ProfileView so this test targets only the route shim's guard + decode,
// not the whole profile tree (covered by ProfileView.test.tsx).
vi.mock("@/components/profile/ProfileView", () => ({
  ProfileView: ({ handle }: { handle: string }) => (
    <div data-testid="profile-view">{handle}</div>
  ),
}))

import ProfilePage from "@/app/[handle]/page"

afterEach(() => {
  paramsRef.current = { handle: "" }
})

describe("/@handle route shim", () => {
  it("renders ProfileView for an @-prefixed handle", () => {
    paramsRef.current = { handle: "@nova" }
    render(<ProfilePage />)
    expect(screen.getByTestId("profile-view")).toHaveTextContent("@nova")
    expect(notFound).not.toHaveBeenCalled()
  })

  it("decodes a percent-encoded handle before handing it off", () => {
    // useParams returns the raw, still-encoded segment (e.g. /%40nova).
    paramsRef.current = { handle: "%40nova" }
    render(<ProfilePage />)
    expect(screen.getByTestId("profile-view")).toHaveTextContent("@nova")
  })

  it("404s a top-level path that isn't a profile (no @)", () => {
    paramsRef.current = { handle: "not-a-profile" }
    expect(() => render(<ProfilePage />)).toThrow("NEXT_NOT_FOUND")
    expect(notFound).toHaveBeenCalled()
  })

  it("404s when the route param is missing", () => {
    paramsRef.current = null
    expect(() => render(<ProfilePage />)).toThrow("NEXT_NOT_FOUND")
    expect(notFound).toHaveBeenCalled()
  })
})
