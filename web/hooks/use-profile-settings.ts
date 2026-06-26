"use client"

import { useCallback, useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { UserProfile, UserProfileUpdate } from "@/lib/profile"

/** Field-keyed error messages mapped from a 409/422 response. */
export type FieldErrors = Partial<
  Record<"display_name" | "handle" | "bio" | "style_tags", string>
>

export type SaveResult =
  | { ok: true; profile: UserProfile }
  | { ok: false; fieldErrors: FieldErrors; message: string | null }

// null = not loaded yet; failed reflects a load error. Loading/error are
// derived from this + auth so the effect never calls setState synchronously.
type Loaded = { profile: UserProfile | null; failed: boolean }

// FastAPI validation error shape: { detail: [{ loc: ["body", field], msg }] }.
type ValidationDetail = { loc: (string | number)[]; msg: string }

const EDITABLE_FIELDS = new Set(["display_name", "handle", "bio", "style_tags"])

function parseErrors(status: number, body: unknown): SaveResult {
  if (status === 409) {
    return {
      ok: false,
      fieldErrors: { handle: "This handle is already taken." },
      message: null,
    }
  }
  if (status === 422 && body && Array.isArray((body as { detail?: unknown }).detail)) {
    const fieldErrors: FieldErrors = {}
    for (const d of (body as { detail: ValidationDetail[] }).detail) {
      const field = d.loc?.[d.loc.length - 1]
      if (typeof field === "string" && EDITABLE_FIELDS.has(field)) {
        fieldErrors[field as keyof FieldErrors] = d.msg
      }
    }
    if (Object.keys(fieldErrors).length > 0) {
      return { ok: false, fieldErrors, message: null }
    }
  }
  const detail = (body as { detail?: unknown })?.detail
  return {
    ok: false,
    fieldErrors: {},
    message: typeof detail === "string" ? detail : "Could not save changes. Please try again.",
  }
}

/**
 * Load the current user's profile and expose a save action. Fetch waits for the
 * in-memory access token (restored on app mount) before calling the same-origin
 * BFF proxy at /api/users/me.
 */
export function useProfileSettings() {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    // accessToken only flips null→token once on mount (logout redirects away),
    // so there's no stale-load reset to do here.
    if (authLoading || !accessToken) return
    let active = true
    fetch("/api/users/me", {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as UserProfile
      })
      .then((profile) => {
        if (active) setLoaded({ profile, failed: false })
      })
      .catch(() => {
        if (active) setLoaded({ profile: null, failed: true })
      })
    return () => {
      active = false
    }
  }, [accessToken, authLoading])

  const isLoading = authLoading || (!!accessToken && loaded === null)
  const error =
    !authLoading && !accessToken
      ? "Not authenticated."
      : loaded?.failed
        ? "Could not load your profile. Please try again."
        : null
  const profile = loaded?.profile ?? null

  const save = useCallback(
    async (update: UserProfileUpdate): Promise<SaveResult> => {
      if (!accessToken) {
        return { ok: false, fieldErrors: {}, message: "Not authenticated." }
      }
      let res: Response
      try {
        res = await fetch("/api/users/me", {
          method: "PATCH",
          headers: {
            authorization: `Bearer ${accessToken}`,
            "content-type": "application/json",
          },
          body: JSON.stringify(update),
        })
      } catch {
        return {
          ok: false,
          fieldErrors: {},
          message: "Network error. Please try again.",
        }
      }
      const body = await res.json().catch(() => ({}))
      if (res.ok) {
        const updated = body as UserProfile
        setLoaded({ profile: updated, failed: false })
        return { ok: true, profile: updated }
      }
      return parseErrors(res.status, body)
    },
    [accessToken]
  )

  return { profile, isLoading, error, save }
}
