import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import SettingsPage from "@/app/settings/page"
import { AuthContext } from "@/contexts/auth-context"

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function renderPage() {
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
    )
  }
  return render(<SettingsPage />, { wrapper })
}

const PROFILE = {
  id: "u1",
  email: "a@b.co",
  name: "Ada",
  display_name: "Ada",
  handle: "ada",
  bio: "hello",
  style_tags: ["cello"],
  avatar_url: null,
  subscription_tier: "free",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => vi.restoreAllMocks())

describe("SettingsPage", () => {
  it("loads and populates the form from the profile", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(PROFILE)))
    renderPage()

    const nameInput = await screen.findByLabelText("Display name")
    expect(nameInput).toHaveValue("Ada")
    expect(screen.getByLabelText("Handle")).toHaveValue("ada")
    expect(screen.getByText("cello")).toBeInTheDocument()
  })

  it("saves changed fields and shows a success message", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(jsonRes({ ...PROFILE, display_name: "Ada L" }))
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    renderPage()

    const nameInput = await screen.findByLabelText("Display name")
    await user.clear(nameInput)
    await user.type(nameInput, "Ada L")
    await user.click(screen.getByRole("button", { name: /Save changes/ }))

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Saved.")
    )
    const patch = fetchMock.mock.calls[1]
    expect(patch[1].method).toBe("PATCH")
    expect(JSON.parse(patch[1].body)).toEqual({ display_name: "Ada L" })
  })

  it("gives real-time format feedback on the handle as you type", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(PROFILE)))
    const user = userEvent.setup()
    renderPage()

    const handleInput = await screen.findByLabelText("Handle")
    await user.clear(handleInput)
    await user.type(handleInput, "ab") // too short
    await waitFor(() =>
      expect(screen.getByText(/3-30 characters/)).toBeInTheDocument()
    )

    await user.type(handleInput, "cde") // now "abcde" — valid
    await waitFor(() =>
      expect(screen.getByText("Looks good")).toBeInTheDocument()
    )
  })

  it("does not flash 'Looks good' while typing an invalid handle", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(PROFILE)))
    const user = userEvent.setup()
    renderPage()

    const handleInput = await screen.findByLabelText("Handle")
    await user.clear(handleInput)
    await user.type(handleInput, "ab") // too short → never valid
    // Synchronous validity gate means the hint never appears, even pre-debounce.
    expect(screen.queryByText("Looks good")).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText(/3-30 characters/)).toBeInTheDocument()
    )
    expect(screen.queryByText("Looks good")).not.toBeInTheDocument()
  })

  it("hides 'Looks good' when a save fails with a form-level error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(jsonRes({}, 500))
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    renderPage()

    const handleInput = await screen.findByLabelText("Handle")
    await user.clear(handleInput)
    await user.type(handleInput, "new-handle") // valid format
    await waitFor(() =>
      expect(screen.getByText("Looks good")).toBeInTheDocument()
    )
    await user.click(screen.getByRole("button", { name: /Save changes/ }))

    await waitFor(() =>
      expect(screen.getByText(/Could not save changes/i)).toBeInTheDocument()
    )
    expect(screen.queryByText("Looks good")).not.toBeInTheDocument()
  })

  it("shows an inline error when the handle is already taken (409)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(jsonRes({ detail: "taken" }, 409))
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    renderPage()

    const handleInput = await screen.findByLabelText("Handle")
    await user.clear(handleInput)
    await user.type(handleInput, "taken-one")
    await user.click(screen.getByRole("button", { name: /Save changes/ }))

    await waitFor(() =>
      expect(screen.getByText(/already taken/i)).toBeInTheDocument()
    )
  })

  it("blocks save and shows a required error when display name is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(PROFILE)))
    const user = userEvent.setup()
    renderPage()

    const nameInput = await screen.findByLabelText("Display name")
    await user.clear(nameInput)
    // dirty the form so the save button enables
    await user.type(screen.getByLabelText("Handle"), "x")
    await user.click(screen.getByRole("button", { name: /Save changes/ }))

    expect(screen.getByText(/required/i)).toBeInTheDocument()
    // The error is associated with the field for assistive tech.
    const nameField = screen.getByLabelText("Display name")
    expect(nameField).toHaveAttribute("aria-describedby", "display_name-error")
    expect(screen.getByText(/required/i)).toHaveAttribute(
      "id",
      "display_name-error"
    )
  })

  it("shows an error state when the profile fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes({}, 500)))
    renderPage()
    await waitFor(() =>
      expect(
        screen.getByText(/Could not load your profile/i)
      ).toBeInTheDocument()
    )
  })

  it("surfaces a session-expired message on a 401 load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "x" }, 401))
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/session expired/i)).toBeInTheDocument()
    )
  })

  it("skips the network round-trip when only trailing whitespace changed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(PROFILE))
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    renderPage()

    const nameInput = await screen.findByLabelText("Display name")
    await user.type(nameInput, "  ") // "Ada  " trims back to "Ada"
    await user.click(screen.getByRole("button", { name: /Save changes/ }))

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Saved.")
    )
    // Only the mount GET fired — no PATCH.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
