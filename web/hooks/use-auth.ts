"use client"

import { useContext } from "react"

import { AuthContext } from "@/contexts/auth-context"

/** Access the auth context. Throws if used outside an AuthProvider. */
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
