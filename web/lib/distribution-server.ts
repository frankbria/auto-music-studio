// Server-only helpers for the SoundCloud BFF routes. Imports next/server, so
// never pull this into a client component. Mirrors lib/auth-server, but for the
// SoundCloud link's PKCE cookies (sc_link_nonce_* / sc_link_verifier_*) which the
// backend sets at /connect and reads back at /callback.
import type { NextRequest, NextResponse } from "next/server"

import { cookieOptions, STATE_MAX_AGE } from "@/lib/auth-server"

/** Prefixes of the backend's per-flow SoundCloud link cookies. */
export const SC_LINK_PREFIXES = ["sc_link_nonce_", "sc_link_verifier_"] as const

function isScLinkCookie(name: string): boolean {
  return SC_LINK_PREFIXES.some((p) => name.startsWith(p))
}

/**
 * Pull the sc_link_* cookies out of a backend Set-Cookie header list, returning
 * just name/value so the BFF can re-emit them under its own path. Cookie
 * attributes (the backend's `/api/v1/distribution` path, secure, etc.) are
 * intentionally dropped — the BFF re-scopes them to `/` so its callback route
 * can read them back. Mirrors auth.parseStateSetCookies.
 */
export function parseScLinkSetCookies(
  setCookies: string[]
): { name: string; value: string }[] {
  const out: { name: string; value: string }[] = []
  for (const raw of setCookies) {
    const pair = raw.split(";", 1)[0]
    const eq = pair.indexOf("=")
    if (eq === -1) continue
    const name = pair.slice(0, eq).trim()
    const value = pair.slice(eq + 1).trim()
    if (isScLinkCookie(name) && value) out.push({ name, value })
  }
  return out
}

/** Re-emit the backend's link cookies on the BFF response, scoped so /callback reads them. */
export function reemitScLinkCookies(response: NextResponse, setCookies: string[]): void {
  for (const { name, value } of parseScLinkSetCookies(setCookies)) {
    response.cookies.set(name, value, cookieOptions(STATE_MAX_AGE))
  }
}

/** Build a `Cookie` header of the sc_link_* cookies to forward back to the backend. */
export function collectScLinkCookies(request: NextRequest): string {
  return request.cookies
    .getAll()
    .filter((c) => isScLinkCookie(c.name))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ")
}

/** Expire the sc_link_* cookies once the link flow is consumed. */
export function clearScLinkCookies(request: NextRequest, response: NextResponse): void {
  for (const c of request.cookies.getAll()) {
    if (isScLinkCookie(c.name)) response.cookies.set(c.name, "", cookieOptions(0))
  }
}
