import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { FeatureFlagAdmin } from "@/components/admin/FeatureFlagAdmin"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const flags = (
  everyone = false,
  users: { id: string; email: string }[] = []
) => ({
  flags: [
    {
      key: "style_transfer",
      name: "Style transfer",
      stage: "beta",
      enabled_for_everyone: everyone,
      users,
    },
  ],
})

describe("FeatureFlagAdmin (#342)", () => {
  it("rolls a feature out to everyone", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(flags())))
      .mockResolvedValueOnce(new Response(JSON.stringify(flags(true))))
    vi.stubGlobal("fetch", fetchMock)
    render(<FeatureFlagAdmin token="tok" />)

    const everyone = await screen.findByRole("switch", { name: "Everyone" })
    await userEvent.click(everyone)

    await waitFor(() => expect(everyone).toBeChecked())
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/admin/feature-flags/style_transfer"
    )
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT")
  })

  it("grants one user by email, and removes them", async () => {
    const granted = [{ id: "u1", email: "fan@example.com" }]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(flags())))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(flags(false, granted)))
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(flags())))
    vi.stubGlobal("fetch", fetchMock)
    render(<FeatureFlagAdmin token="tok" />)

    await userEvent.type(
      await screen.findByLabelText("Grant Style transfer to a user by email"),
      "fan@example.com"
    )
    await userEvent.click(screen.getByRole("button", { name: "Grant" }))
    expect(await screen.findByText("fan@example.com")).toBeInTheDocument()
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/admin/feature-flags/style_transfer/users/fan%40example.com"
    )

    await userEvent.click(
      screen.getByRole("button", {
        name: "Remove fan@example.com from Style transfer",
      })
    )
    await waitFor(() =>
      expect(screen.queryByText("fan@example.com")).toBeNull()
    )
    expect(fetchMock.mock.calls[2][1].method).toBe("DELETE")
  })

  it("shows an unknown email beside the field", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(JSON.stringify(flags())))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ detail: "No user has that email address." }),
            { status: 404 }
          )
        )
    )
    render(<FeatureFlagAdmin token="tok" />)

    const email = await screen.findByLabelText(
      "Grant Style transfer to a user by email"
    )
    await userEvent.type(email, "nobody@example.com")
    await userEvent.click(screen.getByRole("button", { name: "Grant" }))

    await waitFor(() =>
      expect(email).toHaveAccessibleDescription(
        "No user has that email address."
      )
    )
  })
})
