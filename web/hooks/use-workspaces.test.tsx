import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useWorkspaces } from "@/hooks/use-workspaces"

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

function ws(id: string, is_default = false) {
  return {
    id,
    name: id,
    clip_count: 0,
    is_default,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
  }
}

afterEach(() => vi.restoreAllMocks())

describe("useWorkspaces", () => {
  it("loads workspaces and picks the default one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ workspaces: [ws("a"), ws("b", true)], total: 2 }),
          { status: 200 }
        )
      )
    )
    const { result } = renderHook(() => useWorkspaces(), { wrapper })
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.workspaces).toHaveLength(2)
    expect(result.current.defaultWorkspace?.id).toBe("b")
  })

  it("falls back to the first workspace when none is default", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ workspaces: [ws("a"), ws("b")], total: 2 }), {
          status: 200,
        })
      )
    )
    const { result } = renderHook(() => useWorkspaces(), { wrapper })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.defaultWorkspace?.id).toBe("a")
  })

  it("flags an error on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })))
    const { result } = renderHook(() => useWorkspaces(), { wrapper })
    await waitFor(() => expect(result.current.error).toBe(true))
  })
})
