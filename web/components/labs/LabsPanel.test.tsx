import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LabsPanel } from "@/components/labs/LabsPanel"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const experiments = (enabled = false) => ({
  experiments: [
    {
      key: "ai_arrangement",
      name: "AI arrangement",
      description: "Arrange it.",
      stage: "beta",
      available: true,
      enabled,
    },
    {
      key: "real_time_generation",
      name: "Real-time generation",
      description: "Hear it.",
      stage: "alpha",
      available: false,
      enabled: false,
    },
  ],
})

describe("LabsPanel (#342)", () => {
  it("shows each experiment with its stage, and switches an available one on", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(experiments())))
      .mockResolvedValueOnce(new Response(JSON.stringify(experiments(true))))
    vi.stubGlobal("fetch", fetchMock)
    render(
      <SignedIn>
        <LabsPanel />
      </SignedIn>
    )

    const arrangement = await screen.findByRole("switch", {
      name: "AI arrangement",
    })
    expect(screen.getByText("Beta")).toBeInTheDocument()
    expect(screen.getByText("Alpha")).toBeInTheDocument()

    await userEvent.click(arrangement)

    await waitFor(() => expect(arrangement).toBeChecked())
    expect(fetchMock.mock.calls[1][0]).toBe("/api/labs/ai_arrangement")
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      enabled: true,
    })
  })

  it("keeps an unavailable experiment's switch off and says why", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(experiments())))
    )
    render(
      <SignedIn>
        <LabsPanel />
      </SignedIn>
    )

    const realtime = await screen.findByRole("switch", {
      name: "Real-time generation",
    })
    expect(realtime).toBeDisabled()
    expect(realtime).toHaveAccessibleDescription(
      "Not available to your account yet."
    )
  })

  it("asks a signed-out visitor to sign in", () => {
    render(
      <SignedIn
        value={{
          ...{
            user: null,
            accessToken: null,
            isAuthenticated: false,
            isLoading: false,
            login: vi.fn(),
            completeLogin: vi.fn(),
            logout: vi.fn(),
          },
        }}
      >
        <LabsPanel />
      </SignedIn>
    )
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login?from=/labs"
    )
  })
})
