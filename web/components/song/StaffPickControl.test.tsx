import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { StaffPickControl } from "@/components/song/StaffPickControl"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const engagement = (staffPickedAt: string | null) =>
  new Response(
    JSON.stringify({
      play_count: 12,
      like_count: 4,
      share_count: 2,
      staff_picked_at: staffPickedAt,
    })
  )

function renderControl() {
  return render(
    <SignedIn>
      <StaffPickControl clipId="c1" />
    </SignedIn>
  )
}

describe("StaffPickControl (#656)", () => {
  it("shows every count, shares included, and picks the song", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(engagement(null))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ staff_picked_at: "2026-11-02T00:00:00Z" })
        )
      )
    vi.stubGlobal("fetch", fetchMock)
    renderControl()

    expect(
      await screen.findByText(/12 plays · 4 likes · 2 shares/)
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole("button", { name: "Make staff pick" })
    )

    expect(
      await screen.findByRole("button", { name: "Staff pick" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(fetchMock.mock.calls[1][0]).toBe("/api/admin/clips/c1/staff-pick")
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT")
    expect(fetchMock.mock.calls[1][1].headers.authorization).toBe("Bearer tok")
  })

  it("keeps the pick as it was and says so when saving fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(engagement("2026-11-01T00:00:00Z"))
        .mockResolvedValueOnce(new Response("{}", { status: 503 }))
    )
    renderControl()

    await userEvent.click(
      await screen.findByRole("button", { name: "Staff pick" })
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't update the staff pick."
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Staff pick" })).toBeEnabled()
    )
  })

  it("renders nothing when the counts can't be read for a non-admin", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 403 }))
    vi.stubGlobal("fetch", fetchMock)
    const { container } = renderControl()

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(
      container.querySelector("[data-slot=staff-pick-control] button")
    ).toBeNull()
  })
})
