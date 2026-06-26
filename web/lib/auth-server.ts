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
