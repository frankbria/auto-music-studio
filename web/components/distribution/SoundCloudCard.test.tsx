import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { SoundCloudCard } from "@/components/distribution/SoundCloudCard"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: "tok" }) }))

const getSoundCloudStatus = vi.fn()
const connectSoundCloud = vi.fn()
const disconnectSoundCloud = vi.fn()
vi.mock("@/lib/distribution", () => ({
  getSoundCloudStatus: (...a: unknown[]) => getSoundCloudStatus(...a),
  connectSoundCloud: (...a: unknown[]) => connectSoundCloud(...a),
  disconnectSoundCloud: (...a: unknown[]) => disconnectSoundCloud(...a),
}))

beforeEach(() => {
  push.mockReset()
  getSoundCloudStatus.mockReset()
  connectSoundCloud.mockReset()
  disconnectSoundCloud.mockReset()
})
afterEach(() => vi.restoreAllMocks())

const disconnected = {
  kind: "ok" as const,
  status: { connected: false, username: null, connectedAt: null, tokenValid: null },
}
const connected = {
  kind: "ok" as const,
  status: {
    connected: true,
    username: "dj_ams",
    connectedAt: "2026-07-01T00:00:00Z",
    tokenValid: true,
  },
}

describe("SoundCloudCard", () => {
  it("shows a Connect button when disconnected", async () => {
    getSoundCloudStatus.mockResolvedValue(disconnected)
    render(<SoundCloudCard />)
    expect(await screen.findByRole("button", { name: /connect soundcloud/i })).toBeInTheDocument()
  })

  it("redirects to the SoundCloud authorize URL on connect", async () => {
    getSoundCloudStatus.mockResolvedValue(disconnected)
    connectSoundCloud.mockResolvedValue({
      kind: "ok",
      authorizationUrl: "https://soundcloud.com/connect?x=1",
    })
    // window.location.href assignment — capture instead of navigating.
    const location = { href: "" }
    Object.defineProperty(window, "location", { value: location, writable: true })

    render(<SoundCloudCard />)
    await userEvent.click(await screen.findByRole("button", { name: /connect soundcloud/i }))
    await waitFor(() => expect(location.href).toBe("https://soundcloud.com/connect?x=1"))
  })

  it("shows the username, an initials avatar and Disconnect when connected", async () => {
    getSoundCloudStatus.mockResolvedValue(connected)
    render(<SoundCloudCard />)
    expect(await screen.findByText("dj_ams")).toBeInTheDocument()
    expect(screen.getByText("DA")).toBeInTheDocument() // initials placeholder avatar
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument()
  })

  it("disconnects after confirming in the dialog", async () => {
    getSoundCloudStatus.mockResolvedValue(connected)
    disconnectSoundCloud.mockResolvedValue({ kind: "ok" })
    render(<SoundCloudCard />)

    await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }))
    // Confirm inside the dialog (the trigger button has the same label).
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: /^disconnect$/i }))

    await waitFor(() => expect(disconnectSoundCloud).toHaveBeenCalledWith("tok"))
    expect(await screen.findByText(/soundcloud disconnected/i)).toBeInTheDocument()
  })
})
