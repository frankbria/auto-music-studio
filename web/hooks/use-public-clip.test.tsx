import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import { usePublicClip } from "@/hooks/use-public-clip"
import { makeClip } from "@/test/clip-factory"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

const wrapper = ({ children }: { children: ReactNode }) => (
  <SignedIn>
    <PlayerProvider>{children}</PlayerProvider>
  </SignedIn>
)

function renderSong(likedLocally: string[]) {
  window.localStorage.setItem(
    "ams.player.v1",
    JSON.stringify({ likedIds: likedLocally })
  )
  return renderHook(
    () => ({ song: usePublicClip("s1"), liked: usePlayer().state.likedIds }),
    { wrapper }
  )
}

const clipResponse = (viewerLiked: boolean, status = 200) =>
  new Response(
    JSON.stringify(makeClip({ id: "s1", viewer_liked: viewerLiked })),
    {
      status,
    }
  )

describe("usePublicClip like sync (#656)", () => {
  it("takes the viewer's like from a signed-in read, either way", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => clipResponse(false))
    )
    const { result } = renderSong(["s1"])

    await waitFor(() => expect(result.current.song.clip?.id).toBe("s1"))
    expect(result.current.liked).toEqual([])
  })

  it("adds a like made on another device", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => clipResponse(true))
    )
    const { result } = renderSong([])

    await waitFor(() => expect(result.current.liked).toEqual(["s1"]))
  })

  it("leaves the local like alone when the token was refused and the read fell back to anonymous", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("{}", { status: 401 }))
        .mockResolvedValueOnce(clipResponse(false))
    )
    const { result } = renderSong(["s1"])

    await waitFor(() => expect(result.current.song.clip?.id).toBe("s1"))
    expect(result.current.liked).toEqual(["s1"])
  })
})
