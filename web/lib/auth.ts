// Shared, client-safe auth constants and pure helpers. No server-only imports
// here so this module is safe to pull into client components and middleware.

/** httpOnly cookie the BFF uses to hold the backend refresh token. */
export const REFRESH_COOKIE = "ams_refresh_token"

/**
 * httpOnly cookie holding the short-lived access token, scoped to `/api/clips`.
 * Exists so an `<audio src>` (which cannot attach an Authorization header) can
 * still authenticate to the stream proxy for a private clip: the browser sends
 * this cookie automatically. httpOnly keeps it out of client JS; the `/api/clips`
 * path keeps it off every other request. Mirrors the access token's lifetime.
 */
export const ACCESS_COOKIE = "ams_access_token"

/** Prefix of the backend's per-flow OAuth state cookie (`oauth_state_<flow_id>`). */
export const OAUTH_STATE_PREFIX = "oauth_state_"

/** sessionStorage key holding the post-login return path across the OAuth round-trip. */
export const RETURN_TO_KEY = "ams_return_to"

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
 * Base64url-decode a JWT's payload segment into its claims, or null if the
 * token is malformed. Unverified — trust is established server-side; callers use
 * this only to read display identity and timing hints.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1]
    if (!payload) return null
    let b64 = payload.replace(/-/g, "+").replace(/_/g, "/")
    b64 += "=".repeat((4 - (b64.length % 4)) % 4)
    return JSON.parse(atob(b64)) as Record<string, unknown>
  } catch {
    return null
  }
}

/**
 * Decode the (unverified) JWT payload purely to show identity in the UI.
 * Returns null if the token is missing the expected claims or is malformed.
 */
export function decodeAccessToken(token: string): AuthUser | null {
  const claims = decodeJwtPayload(token)
  const sub = claims?.sub
  const email = claims?.email
  if (typeof sub !== "string" || !sub || typeof email !== "string" || !email) {
    return null
  }
  return { id: sub, email }
}

/**
 * Read the (unverified) `exp` claim from a JWT and return it in milliseconds,
 * or null if the token is malformed or carries no numeric `exp`. Used to
 * schedule a refresh-ahead before the access token dies.
 */
export function decodeTokenExp(token: string): number | null {
  const exp = decodeJwtPayload(token)?.exp
  return typeof exp === "number" ? exp * 1000 : null
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
