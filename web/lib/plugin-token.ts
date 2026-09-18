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
