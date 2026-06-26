"use client"

import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"

import { useAuth } from "./use-auth"

/**
 * Redirect to /login (preserving the intended path) once we know the visitor is
 * unauthenticated. Middleware already blocks the no-cookie case; this also
 * covers a present-but-expired session that fails to refresh.
 */
export function useRequireAuth() {
  const auth = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (!auth.isLoading && !auth.isAuthenticated) {
      router.replace(`/login?from=${encodeURIComponent(pathname)}`)
    }
  }, [auth.isLoading, auth.isAuthenticated, pathname, router])

  return auth
}
