import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FeedItemCard } from "@/components/feed/FeedItemCard"
import { PlayerProvider } from "@/contexts/player-context"
import type { FeedItem } from "@/lib/feed"
import { makeClip } from "@/test/clip-factory"
import { SignedIn } from "@/test/signed-in"

// jsdom doesn't implement media playback; stub it so the auto-play effect runs.
let play: ReturnType<typeof vi.fn>
let pause: ReturnType<typeof vi.fn>

beforeEach(() => {
  play = vi.fn().mockResolvedValue(undefined)
  pause = vi.fn()
  HTMLMediaElement.prototype.play = play as unknown as HTMLMediaElement["play"]
  HTMLMediaElement.prototype.pause =
    pause as unknown as HTMLMediaElement["pause"]
})
afterEach(() => vi.restoreAllMocks())

const item: FeedItem = {
  ...makeClip({
    id: "clip-neon",
    title: "Neon Skyline",
    style_tags: ["synthwave", "electronic"],
  }),
  audioUrl: "/api/clips/clip-neon/stream",
}

function renderCard(active: boolean) {
  return render(
    <PlayerProvider>
      <FeedItemCard item={item} active={active} />
    </PlayerProvider>
  )
}

describe("FeedItemCard", () => {
  it("shows title and style tags as overlays and plays the clip's own stream (AC3)", () => {
    renderCard(false)
    expect(
      screen.getByRole("heading", { name: item.title! })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: "Neon Skyline" })
    ).toBeInTheDocument()
    expect(screen.getByTestId("feed-audio")).toHaveAttribute(
      "src",
      item.audioUrl
    )
    for (const tag of item.style_tags) {
      expect(screen.getByText(tag)).toBeInTheDocument()
    }
  })

  it("auto-plays when active and pauses when not (AC2)", () => {
    const { rerender } = renderCard(true)
    expect(play).toHaveBeenCalled()

    rerender(
      <PlayerProvider>
        <FeedItemCard item={item} active={false} />
      </PlayerProvider>
    )
    expect(pause).toHaveBeenCalled()
  })

  it("toggles like state (AC4)", async () => {
    const user = userEvent.setup()
    renderCard(false)
    const like = screen.getByRole("button", { name: "Like" })
    expect(like).toHaveAttribute("aria-pressed", "false")
    await user.click(like)
    expect(screen.getByRole("button", { name: "Liked" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  })

  it("links remix to the song page and inspire to Create (AC4)", () => {
    renderCard(false)
    expect(screen.getByRole("link", { name: "Remix" })).toHaveAttribute(
      "href",
      `/song/${item.id}`
    )
    expect(screen.getByRole("link", { name: "Inspire" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/create?inspiration=${item.id}`)
    )
  })

  it("opens the share dialog (AC4)", async () => {
    const user = userEvent.setup()
    renderCard(false)
    await user.click(screen.getByRole("button", { name: "Share" }))
    expect(await screen.findByRole("dialog")).toBeInTheDocument()
  })

  it("has a Report rail button that opens the report modal (US-27.2)", async () => {
    render(
      <SignedIn>
        <PlayerProvider>
          <FeedItemCard item={item} active={false} />
        </PlayerProvider>
      </SignedIn>
    )
    await userEvent.click(screen.getByRole("button", { name: "Report" }))
    expect(
      screen.getByRole("dialog", { name: "Report clip" })
    ).toBeInTheDocument()
  })
})
