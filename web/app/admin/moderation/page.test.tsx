import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import AdminModerationPage from "@/app/admin/moderation/page"
import { SignedIn } from "@/test/signed-in"

function stubBackend(isAdmin: boolean) {
  const fetchMock = vi.fn(async (url: string) => {
    const body =
      url === "/api/users/me"
        ? { is_admin: isAdmin }
        : url === "/api/admin/moderation/queue"
          ? { items: [] }
          : { entries: [] }
    return new Response(JSON.stringify(body), { status: 200 })
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("/admin/moderation", () => {
  it("shows the dashboard to an admin", async () => {
    const fetchMock = stubBackend(true)
    render(
      <SignedIn>
        <AdminModerationPage />
      </SignedIn>
    )
    expect(
      await screen.findByRole("heading", { name: "Moderation" })
    ).toBeInTheDocument()
    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/moderation/queue",
      expect.anything()
    )
  })

  it("turns a non-admin away without asking for the queue", async () => {
    const fetchMock = stubBackend(false)
    render(
      <SignedIn>
        <AdminModerationPage />
      </SignedIn>
    )
    expect(
      await screen.findByRole("heading", { name: "Admin access required" })
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/users/me", expect.anything())
    )
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/admin"))
    ).toBe(false)
    expect(
      screen.queryByRole("heading", { name: "Moderation" })
    ).not.toBeInTheDocument()
  })
})
