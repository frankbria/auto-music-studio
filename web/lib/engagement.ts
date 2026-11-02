// Client calls for plays, likes, shares and staff picks (#656), through the same-origin BFF.

function authHeaders(token?: string | null): Record<string, string> {
  return token ? { authorization: `Bearer ${token}` } : {}
}

/** A play counts after this much listening (owner decision, #656). */
export const PLAY_THRESHOLD_SECONDS = 30

/**
 * Report a play or a share. Best-effort: a count that fails to land must never interrupt listening or sharing, and
 * the server ignores a repeat inside its window anyway.
 */
export async function reportEngagement(
  clipId: string,
  action: "play" | "share",
  token?: string | null
): Promise<void> {
  try {
    await fetch(`/api/clips/${encodeURIComponent(clipId)}/${action}`, {
      method: "POST",
      headers: authHeaders(token),
    })
  } catch {
    // Network failure: the count is lost, the music is not.
  }
}

/** Why a like didn't save; `status` is the server's answer (404: the clip isn't public, so its like stays local). */
export class LikeSaveError extends Error {
  constructor(readonly status: number) {
    super(`Saving the like failed (${status})`)
  }
}

/** Like or unlike a clip for the signed-in user; resolves to the server's state. Throws when it didn't save. */
export async function saveLike(
  clipId: string,
  liked: boolean,
  token: string
): Promise<{ liked: boolean; like_count: number }> {
  const res = await fetch(`/api/clips/${encodeURIComponent(clipId)}/like`, {
    method: liked ? "PUT" : "DELETE",
    headers: authHeaders(token),
  })
  if (!res.ok) throw new LikeSaveError(res.status)
  return (await res.json()) as { liked: boolean; like_count: number }
}

export type ClipEngagement = {
  play_count: number
  like_count: number
  share_count: number
  staff_picked_at: string | null
}

async function adminRequest<T>(
  path: string,
  method: "GET" | "PUT" | "DELETE",
  token: string
): Promise<T> {
  const res = await fetch(`/api/admin/clips/${path}`, {
    method,
    headers: { accept: "application/json", ...authHeaders(token) },
  })
  if (!res.ok) throw new Error(`Admin request failed (${res.status})`)
  return (await res.json()) as T
}

/** Every count of a clip, shares included (admin only). */
export function getClipEngagement(
  clipId: string,
  token: string
): Promise<ClipEngagement> {
  return adminRequest(`${encodeURIComponent(clipId)}/engagement`, "GET", token)
}

/** Mark or unmark a staff pick (admin only); resolves to the pick date, or null when unmarked. */
export async function setStaffPick(
  clipId: string,
  picked: boolean,
  token: string
): Promise<string | null> {
  const body = await adminRequest<{ staff_picked_at: string | null }>(
    `${encodeURIComponent(clipId)}/staff-pick`,
    picked ? "PUT" : "DELETE",
    token
  )
  return body.staff_picked_at
}
