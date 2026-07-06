import { render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ClipEditor } from "./ClipEditor"
import type { Clip } from "@/lib/workspace-clips"

// Controllable hook returns.
const auth = { isLoading: false, isAuthenticated: true }
let tier: { isFreeTier: boolean; isLoading: boolean }
let clipResult: { clip: Clip | null; loading: boolean; error: boolean; notFound: boolean }
const useClipAudioSpy = vi.fn(() => ({ status: "loading" }) as { status: string })

vi.mock("@/hooks/use-require-auth", () => ({ useRequireAuth: () => auth }))
vi.mock("@/hooks/use-subscription-tier", () => ({
  useSubscriptionTier: () => tier,
}))
vi.mock("@/hooks/use-clip", () => ({ useClip: () => clipResult }))
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: "t" }) }))
vi.mock("@/hooks/use-clip-audio", () => ({
  useClipAudio: (...args: unknown[]) => useClipAudioSpy(...(args as [])),
}))
// next/link renders a plain anchor in jsdom.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const clip = { id: "c1", title: "Test", duration: 10 } as Clip

beforeEach(() => {
  tier = { isFreeTier: false, isLoading: false }
  clipResult = { clip, loading: false, error: false, notFound: false }
})
afterEach(() => vi.clearAllMocks())

describe("ClipEditor Pro gate", () => {
  it("blocks a free-tier user before decoding any audio", () => {
    tier = { isFreeTier: true, isLoading: false }
    render(<ClipEditor clipId="c1" />)
    expect(screen.getByTestId("editor-locked")).toBeInTheDocument()
    // The gate must run before the audio is fetched/decoded.
    expect(useClipAudioSpy).not.toHaveBeenCalled()
  })

  it("waits for the tier to resolve instead of flashing the editor", () => {
    tier = { isFreeTier: true, isLoading: true }
    render(<ClipEditor clipId="c1" />)
    expect(screen.getByTestId("editor-loading")).toBeInTheDocument()
    expect(useClipAudioSpy).not.toHaveBeenCalled()
  })

  it("lets a Pro user through to audio decoding", () => {
    tier = { isFreeTier: false, isLoading: false }
    render(<ClipEditor clipId="c1" />)
    expect(screen.queryByTestId("editor-locked")).not.toBeInTheDocument()
    expect(screen.getByTestId("editor-audio-loading")).toBeInTheDocument()
    expect(useClipAudioSpy).toHaveBeenCalled()
  })
})
