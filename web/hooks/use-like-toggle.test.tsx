import { act, renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import { useLikeToggle } from "@/hooks/use-like-toggle"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function setup(signedIn = true) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    signedIn ? (
      <SignedIn>
        <PlayerProvider>{children}</PlayerProvider>
      </SignedIn>
    ) : (
      <PlayerProvider>{children}</PlayerProvider>
    )
  return renderHook(
    () => ({ toggle: useLikeToggle(), liked: usePlayer().state.likedIds }),
    { wrapper }
  )
}

describe("useLikeToggle (#656)", () => {
  it("keeps the like in this browser when the clip isn't public (404)", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 404 }))
    vi.stubGlobal("fetch", fetchMock)
    const { result } = setup()

    act(() => result.current.toggle("private-clip"))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await act(async () => {})
    expect(result.current.liked).toEqual(["private-clip"])
  })

  it("ignores a second click while the first save is in flight", async () => {
    let finish: (res: Response) => void = () => {}
    const fetchMock = vi.fn(
      () => new Promise<Response>((resolve) => (finish = resolve))
    )
    vi.stubGlobal("fetch", fetchMock)
    const { result } = setup()

    act(() => result.current.toggle("c1"))
    act(() => result.current.toggle("c1"))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.liked).toEqual(["c1"])
    await act(async () =>
      finish(new Response(JSON.stringify({ liked: true, like_count: 1 })))
    )
    act(() => result.current.toggle("c1"))
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.liked).toEqual([])
  })

  it("never calls the server when signed out", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const { result } = setup(false)

    act(() => result.current.toggle("c1"))

    expect(result.current.liked).toEqual(["c1"])
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
