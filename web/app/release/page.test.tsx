import { fireEvent, render, screen } from "@testing-library/react"
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

// Stub the release children: SongSelector/SelectedSongSummary have their own
// tests, so here we only assert the page wires selection/URL correctly.
vi.mock("@/components/release/SongSelector", () => ({
  SongSelector: ({
    onSelect,
    onCancel,
  }: {
    onSelect: (id: string) => void
    onCancel?: () => void
  }) => (
    <div data-testid="song-selector">
      <button onClick={() => onSelect("c2")}>select-c2</button>
      {onCancel && <button onClick={onCancel}>cancel-pick</button>}
    </div>
  ),
}))
// The mastering tab has its own tests and pulls in auth/job hooks; stub it so
// the page test stays focused on selection/URL wiring.
vi.mock("@/components/mastering/mastering-tab", () => ({
  MasteringTab: ({ selectedClip }: { selectedClip: { id: string } | null }) => (
    <div data-testid="mastering-tab">{selectedClip?.id ?? "no-clip"}</div>
  ),
}))
// The distribution target selector (US-21.5) fetches SoundCloud status via useAuth
// and has its own tests; stub it so this page test stays focused on selection/URL
// wiring (mirrors the mastering-tab stub above).
vi.mock("@/components/distribution/TargetSelector", () => ({
  TargetSelector: ({ clip }: { clip: { id: string } | null }) => (
    <div data-testid="target-selector">{clip?.id ?? "no-clip"}</div>
  ),
}))
vi.mock("@/components/release/SelectedSongSummary", () => ({
  SelectedSongSummary: ({
    clip,
    onChangeSong,
  }: {
    clip: { title: string | null }
    onChangeSong: () => void
  }) => (
    <div data-testid="selected-summary">
      <span>{clip.title}</span>
      <button onClick={onChangeSong}>change-song</button>
    </div>
  ),
}))

import { ReleasePageContent } from "@/app/release/page"

afterEach(() => {
  searchParamsRef.current = new URLSearchParams()
  useClip.mockReset()
  vi.clearAllMocks()
  localStorage.clear() // the form auto-saves a draft on unmount — don't leak across tests
})

function noClip() {
  return { clip: null, loading: false, error: false, notFound: false }
}

function foundClip(title = "My Mixdown") {
  return {
    clip: { id: "c1", title, duration: 65, generation_mode: "studio" },
    loading: false,
    error: false,
    notFound: false,
  }
}

describe("ReleasePage", () => {
  it("shows the Mastering and Distribute tabs", () => {
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(screen.getByRole("tab", { name: /mastering/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /distribute/i })).toBeInTheDocument()
  })

  it("defaults to the Mastering tab and shows the selector when no clip is selected", () => {
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(
      screen.getByRole("tab", { name: /mastering/i })
    ).toHaveAttribute("aria-selected", "true")
    expect(screen.getByTestId("song-selector")).toBeInTheDocument()
    // No clip param means we never fetch a clip.
    expect(useClip).toHaveBeenCalledWith(undefined)
  })

  it("preselects the clip from ?clip= and shows its summary (not the selector)", () => {
    searchParamsRef.current = new URLSearchParams("tab=mastering&clip=c1")
    useClip.mockReturnValue(foundClip())
    render(<ReleasePageContent />)
    expect(useClip).toHaveBeenCalledWith("c1")
    expect(screen.getByTestId("selected-summary")).toBeInTheDocument()
    expect(screen.getByText("My Mixdown")).toBeInTheDocument()
    expect(screen.queryByTestId("song-selector")).not.toBeInTheDocument()
  })

  it("writes ?clip= to the URL when a song is selected", async () => {
    useClip.mockReturnValue(noClip())
    const user = userEvent.setup()
    render(<ReleasePageContent />)
    await user.click(screen.getByText("select-c2"))
    expect(replace).toHaveBeenCalledWith("/release?clip=c2")
  })

  it("reopens the selector when Change Song is clicked, then cancel returns to the summary", async () => {
    searchParamsRef.current = new URLSearchParams("tab=mastering&clip=c1")
    useClip.mockReturnValue(foundClip())
    const user = userEvent.setup()
    render(<ReleasePageContent />)

    await user.click(screen.getByText("change-song"))
    expect(screen.getByTestId("song-selector")).toBeInTheDocument()
    expect(screen.queryByTestId("selected-summary")).not.toBeInTheDocument()

    // With a clip still set, the selector offers a cancel back to the summary.
    await user.click(screen.getByText("cancel-pick"))
    expect(screen.getByTestId("selected-summary")).toBeInTheDocument()
  })

  it("shows a not-found state when the preselected clip is missing", () => {
    searchParamsRef.current = new URLSearchParams("clip=gone")
    useClip.mockReturnValue({
      clip: null,
      loading: false,
      error: false,
      notFound: true,
    })
    render(<ReleasePageContent />)
    expect(screen.getByText(/song not found/i)).toBeInTheDocument()
  })

  it("opens the Distribute tab from ?tab=distribute", () => {
    searchParamsRef.current = new URLSearchParams("tab=distribute")
    useClip.mockReturnValue(noClip())
    render(<ReleasePageContent />)
    expect(
      screen.getByRole("tab", { name: /distribute/i })
    ).toHaveAttribute("aria-selected", "true")
  })

  it("renders the distribution metadata form prefilled for the selected song", () => {
    searchParamsRef.current = new URLSearchParams("tab=distribute&clip=c1")
    useClip.mockReturnValue(foundClip())
    render(<ReleasePageContent />)
    // The form's Title field is pre-populated from the clip (US-21.4 AC1).
    expect(screen.getByLabelText(/^title/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /save draft/i })).toBeInTheDocument()
  })

  it("preserves unsaved Distribute-tab edits across a tab switch (Radix unmounts the panel)", () => {
    searchParamsRef.current = new URLSearchParams("tab=distribute&clip=c1")
    useClip.mockReturnValue(foundClip())
    const { rerender } = render(<ReleasePageContent />)
    fireEvent.change(screen.getByLabelText(/album/i), { target: { value: "Night Sessions" } })
    // Switch to Mastering — Radix unmounts the Distribute panel → save-on-unmount fires.
    searchParamsRef.current = new URLSearchParams("tab=mastering&clip=c1")
    rerender(<ReleasePageContent />)
    expect(screen.getByTestId("mastering-tab")).toBeInTheDocument()
    // Back to Distribute — the panel remounts and resumes the auto-saved draft.
    searchParamsRef.current = new URLSearchParams("tab=distribute&clip=c1")
    rerender(<ReleasePageContent />)
    expect(screen.getByLabelText(/album/i)).toHaveValue("Night Sessions")
  })

  it("syncs the URL when switching tabs", async () => {
    useClip.mockReturnValue(noClip())
    const user = userEvent.setup()
    render(<ReleasePageContent />)
    await user.click(screen.getByRole("tab", { name: /distribute/i }))
    expect(replace).toHaveBeenCalledWith("/release?tab=distribute")
  })

  it("keeps ?clip= when switching tabs", async () => {
    searchParamsRef.current = new URLSearchParams("tab=mastering&clip=c1")
    useClip.mockReturnValue(foundClip())
    const user = userEvent.setup()
    render(<ReleasePageContent />)
    await user.click(screen.getByRole("tab", { name: /distribute/i }))
    expect(replace).toHaveBeenCalledWith("/release?tab=distribute&clip=c1")
  })
})
