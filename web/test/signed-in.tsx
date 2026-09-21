import type { ContextType, ReactNode } from "react"
import { vi } from "vitest"

import { AuthContext } from "@/contexts/auth-context"

// A signed-in AuthContext value for components that read the context directly
// (e.g. ReportClipButton) — no AuthProvider, no refresh timers, no network.

export type AuthValue = NonNullable<ContextType<typeof AuthContext>>

export const SIGNED_IN: AuthValue = {
  user: { id: "u1", email: "u@example.com" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

export function SignedIn({
  children,
  value = SIGNED_IN,
}: {
  children: ReactNode
  value?: AuthValue | null
}) {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
