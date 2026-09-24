// Clip moderation appeals (US-27.4): submit an appeal against a removal/flag,
// send more context when an admin asks for it, and read the caller's own
// appeal history. Mirrors lib/reports.ts (same-origin fetch, never throws,
// discriminated result).

export type AppealAction = "remove" | "flag"
export type AppealStatus = "pending" | "info_requested" | "upheld" | "reversed"

export type AppealView = {
  id: string
  clip_id: string
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

async function send(
  method: "POST" | "PATCH",
  clipId: string,
  body: unknown,
  accessToken: string,
  confirmation: string
): Promise<AppealResult> {
  let res: Response
  try {
    res = await fetch(`/api/clips/${encodeURIComponent(clipId)}/appeal`, {
      method,
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    })
  } catch {
    return { status: "error", detail: FALLBACK }
  }
  const responseBody = await res.json().catch(() => null)
  if (res.status === 401)
    return { status: "error", detail: "Sign in to appeal clips." }
  if (!res.ok)
    return { status: "error", detail: detailOf(responseBody) ?? FALLBACK }
  return {
    status: "submitted",
    appeal: responseBody as AppealView,
    message: confirmation,
  }
}

export async function submitClipAppeal(
  clipId: string,
  reason: string,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return send(
    "POST",
    clipId,
    { reason: reason.trim(), context: context.trim() || null },
    accessToken,
    "Appeal submitted. Our team will review it."
  )
}

export async function addAppealContext(
  clipId: string,
  context: string,
  accessToken: string
): Promise<AppealResult> {
  return send(
    "PATCH",
    clipId,
    { context: context.trim() },
    accessToken,
    "Additional information sent."
  )
}

export async function fetchMyAppeals(
  accessToken: string
): Promise<AppealView[]> {
  try {
    const res = await fetch("/api/users/me/appeals", {
      headers: { authorization: `Bearer ${accessToken}` },
    })
    if (!res.ok) return []
    const body = await res.json().catch(() => null)
    return (body as { appeals?: AppealView[] } | null)?.appeals ?? []
  } catch {
    return []
  }
}

const isOpen = (a: AppealView) =>
  a.status === "pending" || a.status === "info_requested"

/**
 * Newest-first input -> one appeal per clip id: the newest still-open one, else
 * the newest. A clip can hold one appeal per decision (a flag and a later
 * removal), and a decided newer appeal must not hide an older open one.
 */
export function latestAppealsByClip(
  appeals: readonly AppealView[]
): Map<string, AppealView> {
  const map = new Map<string, AppealView>()
  for (const appeal of appeals) {
    const kept = map.get(appeal.clip_id)
    if (!kept || (isOpen(appeal) && !isOpen(kept)))
      map.set(appeal.clip_id, appeal)
  }
  return map
}
