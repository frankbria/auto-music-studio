import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

const { searchParamsRef } = vi.hoisted(() => ({
  searchParamsRef: { current: new URLSearchParams() },
}))

const replace = vi.fn()
// This page uses useSearchParams, which the shared setup mock doesn't provide.
vi.mock("next/navigation", () => ({
  usePathname: () => "/release",
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParamsRef.current,
}))

// Auth is always satisfied in these tests — the redirect path is covered by
// useRequireAuth's own tests.
vi.mock("@/hooks/use-require-auth", () => ({
  useRequireAuth: () => ({ isLoading: false, isAuthenticated: true }),
}))

const useClip = vi.fn()
vi.mock("@/hooks/use-clip", () => ({
  useClip: (id: string | undefined) => useClip(id),
}))

import { ReleasePageContent } from "@/app/release/page"

afterEach(() => {
  searchParamsRef.current = new URLSearchParams()
  useClip.mockReset()
  vi.clearAllMocks()
})

function noClip() {
  return { clip: null, loading: false, error: false, notFound: false }
}

describe("ReleasePage", () => {
  it("shows the Mastering and Distribute tabs", () => {
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(screen.getByRole("tab", { name: /mastering/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /distribute/i })).toBeInTheDocument()
  })

  it("defaults to the Mastering tab with an empty state when no clip is selected", () => {
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(
      screen.getByRole("tab", { name: /mastering/i })
    ).toHaveAttribute("aria-selected", "true")
    expect(screen.getByText(/no song selected/i)).toBeInTheDocument()
    // No clip param means we never fetch a clip.
    expect(useClip).toHaveBeenCalledWith(undefined)
  })

  it("preselects the clip from ?clip= and shows its summary", () => {
    searchParamsRef.current = new URLSearchParams("tab=mastering&clip=c1")
    useClip.mockReturnValue({
      clip: { id: "c1", title: "My Mixdown", duration: 65, generation_mode: "studio" },
      loading: false,
      error: false,
      notFound: false,
    })
    render(<ReleasePageContent />)
    expect(useClip).toHaveBeenCalledWith("c1")
    expect(screen.getByText("My Mixdown")).toBeInTheDocument()
    expect(screen.getByText(/1:05/)).toBeInTheDocument()
    expect(screen.getByText(/ready for mastering/i)).toBeInTheDocument()
  })

  it("opens the Distribute tab from ?tab=distribute", () => {
    searchParamsRef.current = new URLSearchParams("tab=distribute")
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(
      screen.getByRole("tab", { name: /distribute/i })
    ).toHaveAttribute("aria-selected", "true")
  })

  it("syncs the URL when switching tabs", async () => {
    useClip.mockReturnValue(noClip())
    const user = userEvent.setup()
    render(<ReleasePageContent />)
    await user.click(screen.getByRole("tab", { name: /distribute/i }))
    expect(replace).toHaveBeenCalledWith("/release?tab=distribute")
  })
})
