import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useMasteringHistory } from "@/hooks/use-mastering-history"
import type { MasteringHistoryItem } from "@/lib/mastering"

const fetchMasteringHistory = vi.fn()
vi.mock("@/lib/mastering", () => ({
  fetchMasteringHistory: (...a: unknown[]) => fetchMasteringHistory(...a),
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
  return (
    <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
  )
}

const jobs: MasteringHistoryItem[] = [
  {
    job_id: "j1",
    status: "completed",
    is_approved: true,
    mastered_clip_id: "m1",
  },
]

afterEach(() => vi.clearAllMocks())

describe("useMasteringHistory", () => {
  it("fetches the clip's mastering jobs", async () => {
    fetchMasteringHistory.mockResolvedValue(jobs)
    const { result } = renderHook(() => useMasteringHistory("c1"), { wrapper })

    await waitFor(() =>
      expect(result.current.state).toEqual({ status: "ready", jobs })
    )
    expect(fetchMasteringHistory).toHaveBeenCalledWith("c1", "tok")
  })

  it("reports an error when the fetch returns null", async () => {
    fetchMasteringHistory.mockResolvedValue(null)
    const { result } = renderHook(() => useMasteringHistory("c1"), { wrapper })
    await waitFor(() => expect(result.current.state.status).toBe("error"))
  })

  it("does not fetch without a clip", () => {
    const { result } = renderHook(() => useMasteringHistory(undefined), {
      wrapper,
    })
    expect(result.current.state.status).toBe("loading")
    expect(fetchMasteringHistory).not.toHaveBeenCalled()
  })

  it("re-fetches when the refresh key changes, keeping the last list meanwhile", async () => {
    fetchMasteringHistory.mockResolvedValue(jobs)
    const { result, rerender } = renderHook(
      ({ key }) => useMasteringHistory("c1", key),
      { wrapper, initialProps: { key: "idle" } }
    )
    await waitFor(() => expect(result.current.state.status).toBe("ready"))

    fetchMasteringHistory.mockReturnValue(new Promise(() => {}))
    rerender({ key: "completed" })
    expect(fetchMasteringHistory).toHaveBeenCalledTimes(2)
    expect(result.current.state).toEqual({ status: "ready", jobs })
  })

  it("does not show one clip's history under another", async () => {
    fetchMasteringHistory.mockResolvedValue(jobs)
    const { result, rerender } = renderHook(
      ({ id }) => useMasteringHistory(id),
      {
        wrapper,
        initialProps: { id: "c1" },
      }
    )
    await waitFor(() => expect(result.current.state.status).toBe("ready"))

    fetchMasteringHistory.mockReturnValue(new Promise(() => {}))
    rerender({ id: "c2" })
    expect(result.current.state.status).toBe("loading")
  })

  it("reload re-fetches", async () => {
    fetchMasteringHistory.mockResolvedValue(null)
    const { result } = renderHook(() => useMasteringHistory("c1"), { wrapper })
    await waitFor(() => expect(result.current.state.status).toBe("error"))

    fetchMasteringHistory.mockResolvedValue(jobs)
    await act(async () => {
      result.current.reload()
    })
    await waitFor(() => expect(result.current.state.status).toBe("ready"))
  })
})
