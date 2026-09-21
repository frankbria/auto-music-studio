// Admin moderation dashboard client (US-27.3). Every call goes through the
// same-origin /api/admin proxy; the backend's require_admin is the real gate.

import type { ReportCategory } from "@/lib/reports"

export type QueueSource = "report" | "automated"

export type QueueItem = {
  clip_id: string
  /** Reports can outlive their clip; title and creator are null then. */
  clip_deleted: boolean
  title: string | null
  style_tags: string[]
  creator_id: string | null
  creator_name: string | null
  creator_banned: boolean
  visibility: "private" | "unlisted" | "public" | null
  content_warning: boolean
  report_count: number
  categories: Partial<Record<ReportCategory, number>>
  moderation_flags: string[]
  sources: QueueSource[]
  severity: number
  latest_at: string
}

export type ModerationLogEntry = {
  id: string
  actor_id: string
  action: string
  target_type: string
  target_id: string
  reason: string | null
  details: Record<string, unknown>
  created_at: string
}

export type ClipAction = "approve" | "remove" | "flag"
export type UserAction = "warn" | "ban"

/** One target's outcome; a bulk action can partly fail. */
export type ActionResult = { id: string; ok: boolean; detail: string | null }

export type QueueSort = "reports" | "severity" | "newest"
export type SourceFilter = "all" | QueueSource
export type CategoryFilter = "all" | ReportCategory

export class ModerationError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message)
    this.name = "ModerationError"
  }
}

const FALLBACK = "Moderation service is unavailable."

function detailOf(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === "string" ? detail : null
}

async function request<T>(
  path: string,
  token: string,
  body?: unknown
): Promise<T> {
  const init: RequestInit = {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  }
  if (body !== undefined) {
    init.method = "POST"
    init.headers = {
      ...init.headers,
      "content-type": "application/json",
    }
    init.body = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(`/api/admin/moderation/${path}`, init)
  } catch {
    throw new ModerationError(FALLBACK, 0)
  }
  const json = await res.json().catch(() => null)
  if (!res.ok) throw new ModerationError(detailOf(json) ?? FALLBACK, res.status)
  return json as T
}

export async function fetchModerationQueue(
  token: string
): Promise<QueueItem[]> {
  return (await request<{ items: QueueItem[] }>("queue", token)).items
}

export async function fetchModerationLog(
  token: string,
  limit = 100
): Promise<ModerationLogEntry[]> {
  return (
    await request<{ entries: ModerationLogEntry[] }>(
      `log?limit=${limit}`,
      token
    )
  ).entries
}

function withReason(body: Record<string, unknown>, reason?: string) {
  const trimmed = reason?.trim()
  return trimmed ? { ...body, reason: trimmed } : body
}

type RawResult = { ok: boolean; detail?: string | null }

/** The backend rejects (422) a batch of more than this many ids. */
export const MAX_BATCH = 100

// "Select all" can cover the whole 500-row queue, so large selections go out as
// sequential batches. A failed batch throws; earlier batches have already applied,
// which the caller's refetch shows.
async function inBatches(
  ids: string[],
  send: (batch: string[]) => Promise<ActionResult[]>
): Promise<ActionResult[]> {
  const results: ActionResult[] = []
  for (let i = 0; i < ids.length; i += MAX_BATCH)
    results.push(...(await send(ids.slice(i, i + MAX_BATCH))))
  return results
}

export async function applyClipAction(
  token: string,
  action: ClipAction,
  clipIds: string[],
  reason?: string
): Promise<ActionResult[]> {
  return inBatches(clipIds, async (batch) => {
    const { results } = await request<{
      results: (RawResult & { clip_id: string })[]
    }>("clips", token, withReason({ action, clip_ids: batch }, reason))
    return results.map((r) => ({
      id: r.clip_id,
      ok: r.ok,
      detail: r.detail ?? null,
    }))
  })
}

export async function applyUserAction(
  token: string,
  action: UserAction,
  userIds: string[],
  reason?: string
): Promise<ActionResult[]> {
  return inBatches(userIds, async (batch) => {
    const { results } = await request<{
      results: (RawResult & { user_id: string })[]
    }>("users", token, withReason({ action, user_ids: batch }, reason))
    return results.map((r) => ({
      id: r.user_id,
      ok: r.ok,
      detail: r.detail ?? null,
    }))
  })
}

/** "reports" is the server's own order (report count, severity, recency). */
export function sortQueue(items: QueueItem[], sort: QueueSort): QueueItem[] {
  if (sort === "reports") return items
  const copy = [...items]
  if (sort === "severity")
    copy.sort(
      (a, b) => b.severity - a.severity || b.report_count - a.report_count
    )
  else copy.sort((a, b) => Date.parse(b.latest_at) - Date.parse(a.latest_at))
  return copy
}

export function filterQueue(
  items: QueueItem[],
  source: SourceFilter,
  category: CategoryFilter
): QueueItem[] {
  return items.filter(
    (i) =>
      (source === "all" || i.sources.includes(source)) &&
      (category === "all" || (i.categories[category] ?? 0) > 0)
  )
}

const LOG_ACTION_LABELS: Record<string, string> = {
  approve: "Approved clip",
  remove: "Removed clip",
  flag: "Flagged clip",
  warn: "Warned user",
  ban: "Banned user",
  update_screening_rules: "Updated screening rules",
}

export function formatLogAction(action: string): string {
  return LOG_ACTION_LABELS[action] ?? action.replaceAll("_", " ")
}

// The API serializes naive UTC datetimes (no offset); `new Date` would read those as local time.
export function parseApiTime(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`)
}
