import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useClipAudio } from "@/hooks/use-clip-audio"

// The decode is the expensive part (fetch + Web Audio decode) — mock it so we
// can count how often it runs across token rotations.
vi.mock("@/lib/audio-peaks", () => ({
  decodeClipAudio: vi.fn(async () => ({ sampleRate: 48000, peaks: new Float32Array(0) })),
}))

import { decodeClipAudio } from "@/lib/audio-peaks"

const mockDecode = vi.mocked(decodeClipAudio)

afterEach(() => {
  mockDecode.mockClear()
})

describe("useClipAudio", () => {
  it("decodes once and does not re-decode when the token rotates", async () => {
    const { result, rerender } = renderHook(
      ({ token }) => useClipAudio("clip-1", token),
      { initialProps: { token: "tok-1" } }
    )
    await waitFor(() => expect(result.current.status).toBe("ready"))
    expect(mockDecode).toHaveBeenCalledTimes(1)

    // A background auth refresh hands the editor a new token — the already
    // decoded buffer must not be re-fetched/re-decoded (#285 ripple).
    rerender({ token: "tok-2" })
    rerender({ token: "tok-3" })
    expect(mockDecode).toHaveBeenCalledTimes(1)
  })

  it("re-decodes when the clip id changes", async () => {
    const { result, rerender } = renderHook(
      ({ id }) => useClipAudio(id, "tok-1"),
      { initialProps: { id: "clip-1" } }
    )
    await waitFor(() => expect(result.current.status).toBe("ready"))
    rerender({ id: "clip-2" })
    await waitFor(() => expect(mockDecode).toHaveBeenCalledTimes(2))
    expect(mockDecode).toHaveBeenLastCalledWith(
      "clip-2",
      "tok-1",
      expect.any(AbortSignal)
    )
  })

  it("kicks off the decode once the token arrives (null → present)", async () => {
    const { result, rerender } = renderHook(
      ({ token }: { token: string | null }) => useClipAudio("clip-1", token),
      { initialProps: { token: null as string | null } }
    )
    expect(mockDecode).not.toHaveBeenCalled()
    expect(result.current.status).toBe("loading")

    rerender({ token: "tok-1" })
    await waitFor(() => expect(result.current.status).toBe("ready"))
    expect(mockDecode).toHaveBeenCalledTimes(1)
  })
})
