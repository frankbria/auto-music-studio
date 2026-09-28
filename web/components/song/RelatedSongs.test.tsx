import { render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { RelatedSongs } from "@/components/song/RelatedSongs"
import { PlayerProvider } from "@/contexts/player-context"
import { makeClip } from "@/test/clip-factory"
import { SignedIn } from "@/test/signed-in"
import type { Clip } from "@/lib/workspace-clips"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false }),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/song/seed",
}))

function renderRail(similar: Clip[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ clips: similar, total: similar.length, limit: 6 }),
          { status: 200 }
        )
      )
    )
  )
  return render(
    <SignedIn>
      <PlayerProvider>
        <RelatedSongs clipId="seed" />
      </PlayerProvider>
    </SignedIn>
  )
}

async function itemFor(title: string) {
  return (await screen.findByText(title)).closest("li") as HTMLElement
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("RelatedSongs Report control (#535)", () => {
  it("offers Report on another user's clip and hides it on your own", async () => {
    renderRail([
      makeClip({ id: "theirs", title: "Theirs", is_owner: false }),
      makeClip({ id: "mine", title: "Mine", is_owner: true }),
    ])

    const theirs = await itemFor("Theirs")
    expect(
      within(theirs).getByRole("button", { name: "Report" })
    ).toBeInTheDocument()
    const mine = await itemFor("Mine")
    expect(
      within(mine).queryByRole("button", { name: "Report" })
    ).not.toBeInTheDocument()
  })

  it("hides Report when ownership is unknown", async () => {
    renderRail([makeClip({ id: "legacy", title: "Legacy" })])

    const legacy = await itemFor("Legacy")
    expect(
      within(legacy).queryByRole("button", { name: "Report" })
    ).not.toBeInTheDocument()
  })
})
