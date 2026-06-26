// Shared, client-safe auth constants and pure helpers. No server-only imports
// here so this module is safe to pull into client components and middleware.

/** httpOnly cookie the BFF uses to hold the backend refresh token. */
export const REFRESH_COOKIE = "ams_refresh_token"

/** Prefix of the backend's per-flow OAuth state cookie (`oauth_state_<flow_id>`). */
export const OAUTH_STATE_PREFIX = "oauth_state_"

export type AuthUser = { id: string; email: string }

/** OAuth providers the UI and BFF support. */
export const OAUTH_PROVIDERS = ["google", "discord"] as const

export function isSupportedProvider(provider: string): boolean {
  return (OAUTH_PROVIDERS as readonly string[]).includes(provider)
}

/**
 * Clamp a post-login redirect target to a same-site absolute path. Rejects
 * external (`//host`, `/\host`), absolute, and protocol URLs so a crafted
 * `?from=` can't turn the login into an open redirect.
 */
export function safeInternalPath(raw: string | null, fallback = "/create"): string {
  if (raw && raw[0] === "/" && raw[1] !== "/" && raw[1] !== "\\") return raw
  return fallback
}

/**
 * Decode the (unverified) JWT payload purely to show identity in the UI. The
 * token's trust is established server-side; this is display-only. Returns null
 * if the token is missing the expected claims or is malformed.
 */
export function decodeAccessToken(token: string): AuthUser | null {
  try {
    const payload = token.split(".")[1]
    if (!payload) return null
    let b64 = payload.replace(/-/g, "+").replace(/_/g, "/")
    b64 += "=".repeat((4 - (b64.length % 4)) % 4)
    const claims = JSON.parse(atob(b64)) as { sub?: string; email?: string }
    if (!claims.sub || !claims.email) return null
    return { id: claims.sub, email: claims.email }
  } catch {
    return null
  }
}

/**
 * Pull `oauth_state_*` cookies out of a backend `Set-Cookie` header list,
 * returning just the `name`/`value` so the BFF can re-emit them under its own
 * path. Cookie attributes (path/secure/etc.) are intentionally dropped.
 */
export function parseStateSetCookies(
  setCookies: string[]
): { name: string; value: string }[] {
  const out: { name: string; value: string }[] = []
  for (const raw of setCookies) {
    const pair = raw.split(";", 1)[0]
    const eq = pair.indexOf("=")
    if (eq === -1) continue
    const name = pair.slice(0, eq).trim()
    const value = pair.slice(eq + 1).trim()
    if (name.startsWith(OAUTH_STATE_PREFIX) && value) out.push({ name, value })
  }
  return out
}
