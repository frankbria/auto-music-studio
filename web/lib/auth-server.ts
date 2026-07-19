// Server-only auth helpers for the BFF route handlers. Imports next/server, so
// never pull this into a client component.
import type { NextRequest, NextResponse } from "next/server"

import { OAUTH_STATE_PREFIX } from "./auth"

/** Backend base URL the BFF proxies to. Server-side only, so not NEXT_PUBLIC_. */
export const BACKEND_URL = process.env.API_BASE_URL ?? "http://localhost:8000"

/** Matches the backend's 10-minute OAuth state TTL. */
export const STATE_MAX_AGE = 10 * 60
/** Matches the backend's 7-day refresh-token TTL. */
export const REFRESH_MAX_AGE = 7 * 24 * 60 * 60

/** Standard cookie options. Path `/` so middleware can read the session cookie. */
export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  }
}

/** Fallback access-cookie lifetime (15 min) when the backend omits `expires_in`. */
const ACCESS_COOKIE_FALLBACK_MAX_AGE = 15 * 60

/**
 * Cookie options for the access token, scoped to `/api/clips` so the token is
 * only sent on clip media requests (the `<audio>` stream proxy) rather than
 * every request to the app. `maxAge` mirrors the token's `expires_in`.
 */
export function accessCookieOptions(maxAge: number | undefined) {
  // A finite number (including 0, used to clear the cookie) is honoured as-is;
  // only a missing/malformed `expires_in` falls back to the default lifetime.
  const resolved =
    typeof maxAge === "number" && Number.isFinite(maxAge)
      ? maxAge
      : ACCESS_COOKIE_FALLBACK_MAX_AGE
  return { ...cookieOptions(resolved), path: "/api/clips" }
}

/** Build a `Cookie` header of the `oauth_state_*` cookies to forward to the backend. */
export function collectStateCookies(request: NextRequest): string {
  return request.cookies
    .getAll()
    .filter((c) => c.name.startsWith(OAUTH_STATE_PREFIX))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ")
}

/** Expire any `oauth_state_*` cookies on the response once the flow is consumed. */
export function clearStateCookies(request: NextRequest, response: NextResponse) {
  for (const c of request.cookies.getAll()) {
    if (c.name.startsWith(OAUTH_STATE_PREFIX)) {
      response.cookies.set(c.name, "", cookieOptions(0))
    }
  }
}
