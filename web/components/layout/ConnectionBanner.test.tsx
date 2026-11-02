import { act, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ConnectionBanner } from "@/components/layout/ConnectionBanner"

const refresh = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }))

function goOnline(online: boolean) {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(online)
  act(() => {
    window.dispatchEvent(new Event(online ? "online" : "offline"))
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  refresh.mockClear()
})

describe("ConnectionBanner (#339)", () => {
  it("shows nothing while online", () => {
    render(<ConnectionBanner />)
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("tells the user the connection dropped, then clears and refreshes when it's back", () => {
    render(<ConnectionBanner />)

    goOnline(false)
    expect(screen.getByRole("status")).toHaveTextContent("Connection lost")
    expect(refresh).not.toHaveBeenCalled()

    goOnline(true)
    expect(screen.queryByRole("status")).toBeNull()
    expect(refresh).toHaveBeenCalledOnce()
  })
})
