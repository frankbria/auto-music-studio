// Public creator profile reads (US-20.5, #654) through the same-origin BFF
// (app/api/discover/profiles).

import type { Clip } from "@/lib/workspace-clips"

/** GET /api/v1/discover/profiles/{handle}. */
export type PublicProfile = {
  /** Bare handle, no leading "@". The URL adds the "@". */
  handle: string
  display_name: string | null
  bio: string | null
  style_tags: string[]
  joined_at: string
  /** The owner's newest public clips (at most 50). */
  clips: Clip[]
}

/** The public profile for `handle` ("@nova" or "nova"), or null when there is no such creator. */
export async function fetchPublicProfile(
  handle: string,
  token?: string | null
): Promise<PublicProfile | null> {
  const res = await fetch(
    `/api/discover/profiles/${encodeURIComponent(handle.replace(/^@/, ""))}`,
    {
      headers: {
        accept: "application/json",
        // Lets the API mark the viewer's own clips (#653).
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
    }
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Profile request failed (${res.status})`)
  return (await res.json()) as PublicProfile
}
