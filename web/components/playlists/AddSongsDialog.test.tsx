import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AddSongsDialog } from "@/components/playlists/AddSongsDialog"
import { makeClip } from "@/test/clip-factory"
import {
  clipRequests,
  discoverPage,
  stubDiscoverFetch,
} from "@/test/discover-api"
import { SignedIn } from "@/test/signed-in"

const NEON = makeClip({ id: "neon", title: "Neon Skyline", is_public: true })
const PULSE = makeClip({ id: "pulse", title: "Pulse Theory", is_public: true })

function renderDialog(
  props: Partial<Parameters<typeof AddSongsDialog>[0]> = {}
) {
  const onAdd = vi.fn()
  render(
    <AddSongsDialog
      open
      existingIds={[]}
      onAdd={onAdd}
      onOpenChange={vi.fn()}
      {...props}
    />
  )
  return onAdd
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("AddSongsDialog (#654)", () => {
  it("lists the newest public clips before anything is typed", async () => {
    const fetchMock = stubDiscoverFetch(() => discoverPage([NEON, PULSE]))
    renderDialog()

    expect(screen.getByText(/Loading songs/)).toBeInTheDocument()
    expect(await screen.findByText("Neon Skyline")).toBeInTheDocument()
    expect(screen.getByText("Pulse Theory")).toBeInTheDocument()
    expect(clipRequests(fetchMock)).toEqual([{ sort: "newest" }])
  })

  it("searches public clips by the debounced query", async () => {
    const fetchMock = stubDiscoverFetch((url) =>
      discoverPage(url.includes("q=pulse") ? [PULSE] : [NEON, PULSE])
    )
    renderDialog()
    await screen.findByText("Neon Skyline")

    await userEvent.type(
      screen.getByRole("searchbox", { name: "Search songs to add" }),
      "pulse"
    )
    await waitFor(() => {
      expect(screen.queryByText("Neon Skyline")).not.toBeInTheDocument()
      expect(screen.getByText("Pulse Theory")).toBeInTheDocument()
    })
    // One request for the settled query, not one per keystroke.
    expect(clipRequests(fetchMock)).toEqual([
      { sort: "newest" },
      { q: "pulse", sort: "relevance" },
    ])
  })

  it("shows an empty state when nothing matches", async () => {
    stubDiscoverFetch(() => discoverPage([]))
    renderDialog()
    expect(
      await screen.findByText("No public songs found.")
    ).toBeInTheDocument()
  })

  it("shows an error with a retry", async () => {
    let fail = true
    stubDiscoverFetch(() =>
      fail ? new Response("{}", { status: 502 }) : discoverPage([NEON])
    )
    renderDialog()

    expect(await screen.findByText("Couldn't load songs.")).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("Neon Skyline")).toBeInTheDocument()
  })

  it("hands the whole clip to onAdd and marks songs already in the playlist", async () => {
    stubDiscoverFetch(() => discoverPage([NEON, PULSE]))
    const onAdd = renderDialog({ existingIds: ["pulse"] })
    await screen.findByText("Neon Skyline")

    await userEvent.click(
      screen.getByRole("button", { name: "Add Neon Skyline" })
    )
    expect(onAdd).toHaveBeenCalledWith(NEON)
    const pulseRow = screen.getByText("Pulse Theory").closest("li")!
    expect(within(pulseRow).getByText("Added")).toBeInTheDocument()
  })

  it("sends the signed-in viewer's token", async () => {
    const fetchMock = stubDiscoverFetch(() => discoverPage([NEON]))
    render(
      <SignedIn>
        <AddSongsDialog
          open
          existingIds={[]}
          onAdd={vi.fn()}
          onOpenChange={vi.fn()}
        />
      </SignedIn>
    )
    await screen.findByText("Neon Skyline")
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer tok")
  })
})
