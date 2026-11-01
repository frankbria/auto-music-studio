// Moderation appeals (US-27.4): submit an appeal against a clip's removal/flag
// or a video's unpublish (#623), send more context when an admin asks for it,
// and read the caller's own appeal history. Mirrors lib/reports.ts (same-origin fetch, never throws,
// discriminated result).

export type AppealAction = "remove" | "flag" | "unpublish"
export type AppealStatus = "pending" | "info_requested" | "upheld" | "reversed"

export type AppealView = {
  id: string
  /** For a video appeal, the video's song. */
  clip_id: string
  /** Set on an appeal of a video unpublish (#623). */
  video_id?: string | null
  action: AppealAction
  reason: string
  context: string | null
  status: AppealStatus
  admin_note: string | null
  created_at: string
  decided_at: string | null
}

export type AppealResult =
  | { status: "submitted"; appeal: AppealView; message: string }
  | { status: "error"; detail: string }

const FALLBACK = "Could not submit the appeal. Please try again."

function detailOf(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === "string" ? detail : null
}

/** What an appeal is filed against: a clip, or one of its videos (#623). */
export type AppealTarget = { kind: "clip" | "video"; id: string }

const TARGET_PATH: Record<AppealTarget["kind"], string> = {
  clip: "/api/clips",
  video: "/api/videos",
}

async function send(
  method: "POST" | "PATCH",
  target: AppealTarget,
  body: unknown,
  accessToken: string,
  confirmation: string
): Promise<AppealResult> {
  let res: Response
  try {
    res = await fetch(
      `${TARGET_PATH[target.kind]}/${encodeURIComponent(target.id)}/appeal`,
      {
        method,
        headers: {
          authorization: `Bearer ${accessToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
      }
    )
  } catch {
    return { status: "error", detail: FALLBACK }
  }
  const responseBody = await res.json().catch(() => null)
  if (res.status === 401)
    return { status: "error", detail: "Sign in to appeal." }
  if (!res.ok)
    return { status: "error", detail: detailOf(responseBody) ?? FALLBACK }
  return {
    status: "submitted",
    appeal: responseBody as AppealView,
    message: confirmation,
  }
}

export async function submitAppeal(
  target: AppealTarget,
  reason: string,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return send(
    "POST",
    target,
    { reason: reason.trim(), context: context.trim() || null },
    accessToken,
    "Appeal submitted. Our team will review it."
  )
}

export async function submitClipAppeal(
  clipId: string,
  reason: string,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return submitAppeal(
    { kind: "clip", id: clipId },
    reason,
    context,
    accessToken
  )
}

export async function addContext(
  target: AppealTarget,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return send(
    "PATCH",
    target,
    { context: context.trim() },
    accessToken,
    "Additional information sent."
  )
}

/**
 * Every appeal the caller has made, newest first. Walks the server's pages
 * (#543) because the Library matches each clip card to its appeal; a failed
 * page ends the walk with what was already read.
 */
export async function fetchMyAppeals(
  accessToken: string
): Promise<AppealView[]> {
  const appeals: AppealView[] = []
  let cursor: string | null = null
  do {
    const params = new URLSearchParams({ limit: "500" })
    if (cursor) params.set("cursor", cursor)
    const page: { appeals?: AppealView[]; next_cursor?: string | null } | null =
      await fetch(`/api/users/me/appeals?${params}`, {
        headers: { authorization: `Bearer ${accessToken}` },
      })
        .then((res) => (res.ok ? res.json() : null))
        .catch(() => null)
    if (!page) break
    appeals.push(...(page.appeals ?? []))
    cursor = page.next_cursor ?? null
  } while (cursor)
  return appeals
}

export async function addAppealContext(
  clipId: string,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return addContext({ kind: "clip", id: clipId }, context, accessToken)
}

/** The newest appeal against this video's unpublishes (#623); input is newest first. */
export function appealForVideo(
  appeals: readonly AppealView[],
  videoId: string
): AppealView | null {
  return appeals.find((appeal) => appeal.video_id === videoId) ?? null
}

/** Newest-first input -> each clip's appeals, still newest first. Video
 * appeals carry their song's clip_id, so they're left out (#623). */
export function appealsByClip(
  appeals: readonly AppealView[]
): Map<string, AppealView[]> {
  const map = new Map<string, AppealView[]>()
  for (const appeal of appeals) {
    if (appeal.video_id) continue
    const list = map.get(appeal.clip_id)
    if (list) list.push(appeal)
    else map.set(appeal.clip_id, [appeal])
  }
  return map
}

/**
 * The appeal that describes the clip's current state. A clip holds one appeal
 * per decision (a flag, then a removal), so pick the newest one on the decision
 * in force, and fall back to the newest once the clip is clear.
 */
export function appealFor(
  clip: { removed_at?: string | null; content_warning?: boolean },
  appeals: readonly AppealView[]
): AppealView | null {
  const action =
    clip.removed_at != null ? "remove" : clip.content_warning ? "flag" : null
  return (
    (action && appeals.find((a) => a.action === action)) || appeals[0] || null
  )
}
