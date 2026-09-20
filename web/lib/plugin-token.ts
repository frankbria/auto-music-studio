// Plugin token client (issue #445). Thin wrapper over the same-origin proxy in
// app/api/auth/plugin-token, kept out of the component so the component stays
// about rendering.

/**
 * Mint a new plugin token. The backend response also carries its own
 * access_token, but the BFF route strips that before it reaches the browser —
 * the plugin only ever needs the refresh_token.
 */
export async function createPluginToken(accessToken: string): Promise<string> {
  const res = await fetch("/api/auth/plugin-token", {
    method: "POST",
    headers: { authorization: `Bearer ${accessToken}` },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(body.detail || "Could not create a plugin token.")
  }
  if (!body.refresh_token) {
    throw new Error("Malformed token response from the server.")
  }
  return body.refresh_token as string
}

/**
 * A live plugin token, as the settings card lists it (issue #515). The token
 * value itself is never returned — only the id, which revoke takes.
 */
export type PluginTokenSummary = {
  id: string
  created_at: string
  expires_at: string
}

/** List the caller's live plugin tokens, newest first. */
export async function listPluginTokens(
  accessToken: string
): Promise<PluginTokenSummary[]> {
  const res = await fetch("/api/auth/plugin-tokens", {
    headers: { authorization: `Bearer ${accessToken}` },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(body.detail || "Could not load your plugin tokens.")
  }
  // A 200 that is not an array means something answered for the backend (an
  // ingress error page, a truncated body). Returning [] there would tell a
  // musician with live DAW credentials that they have none to revoke — the one
  // wrong answer this card must never give.
  if (!Array.isArray(body)) {
    throw new Error("Could not load your plugin tokens.")
  }
  return body as PluginTokenSummary[]
}

/** Revoke one plugin token. Idempotent on the backend; a 204 carries no body. */
export async function revokePluginToken(
  accessToken: string,
  id: string
): Promise<void> {
  const res = await fetch(`/api/auth/plugin-tokens/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { authorization: `Bearer ${accessToken}` },
  })
  if (res.ok) return
  const body = await res.json().catch(() => ({}))
  throw new Error(body.detail || "Could not revoke that plugin token.")
}
