import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useMasteringPreviews } from "@/hooks/use-mastering-previews"
import type { PreviewsResponse } from "@/lib/mastering"

const fetchMasteringPreviews = vi.fn()
vi.mock("@/lib/mastering", () => ({
  fetchMasteringPreviews: (...a: unknown[]) => fetchMasteringPreviews(...a),
}))

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function wrapper({ children }: { children: ReactNode }) {
  return <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
}

const previews: PreviewsResponse = {
  source_clip_id: "c1",
  original_audio_url: "orig",
  original_metrics: { loudness: -20 },
  previews: [
    { preview_id: "m1", audio_url: "u1", loudness_delta: 6 },
    { preview_id: "m2", audio_url: "u2", loudness_delta: 4 },
  ],
}

afterEach(() => vi.clearAllMocks())

describe("useMasteringPreviews", () => {
  it("fetches previews for the job and defaults selection to the first", async () => {
    fetchMasteringPreviews.mockResolvedValue(previews)
    const { result } = renderHook(() => useMasteringPreviews("j1"), { wrapper })

    await waitFor(() => expect(result.current.state.status).toBe("ready"))
    expect(fetchMasteringPreviews).toHaveBeenCalledWith("j1", "tok")
    expect(result.current.selectedId).toBe("m1")
  })

  it("lets the user select a different preview", async () => {
    fetchMasteringPreviews.mockResolvedValue(previews)
    const { result } = renderHook(() => useMasteringPreviews("j1"), { wrapper })
    await waitFor(() => expect(result.current.state.status).toBe("ready"))

    act(() => result.current.select("m2"))
    expect(result.current.selectedId).toBe("m2")
  })

  it("reports an error when the fetch returns null", async () => {
    fetchMasteringPreviews.mockResolvedValue(null)
    const { result } = renderHook(() => useMasteringPreviews("j1"), { wrapper })
    await waitFor(() => expect(result.current.state.status).toBe("error"))
    expect(result.current.selectedId).toBeNull()
  })

  it("stays loading when no job id is given", () => {
    const { result } = renderHook(() => useMasteringPreviews(undefined), { wrapper })
    expect(result.current.state.status).toBe("loading")
    expect(fetchMasteringPreviews).not.toHaveBeenCalled()
  })

  it("reload re-fetches", async () => {
    fetchMasteringPreviews.mockResolvedValue(previews)
    const { result } = renderHook(() => useMasteringPreviews("j1"), { wrapper })
    await waitFor(() => expect(result.current.state.status).toBe("ready"))
    expect(fetchMasteringPreviews).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.reload()
    })
    await waitFor(() => expect(fetchMasteringPreviews).toHaveBeenCalledTimes(2))
  })
})
