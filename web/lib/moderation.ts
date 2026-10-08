// Admin moderation dashboard client (US-27.3). Every call goes through the
// same-origin /api/admin proxy; the backend's require_admin is the real gate.

import type { AppealView } from "@/lib/appeals"
import type { ReportCategory } from "@/lib/reports"

export type QueueSource = "report" | "automated"
/** #539: flagged videos, generated artwork and voice models share the queue with clips. */
export type ContentType = "video" | "artwork" | "voice_model"
export type QueueTarget = "clip" | ContentType

export type QueueItem = {
  target_type: QueueTarget
  target_id: string
  /** The clip itself, or the song a video or artwork was made for; null for a voice model. */
  clip_id: string | null
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
  /** A video or artwork job's prompt, or a voice model's description. */
  description?: string | null
  published?: boolean | null
}

export type ModerationLogEntry = {
  id: string
  actor_id: string | null
  /** Resolved at read time (#540); null when the admin or target no longer exists. */
  actor_name: string | null
  action: string
  target_type: string
  target_id: string | null
  /** A clip's title, a user's name, a video's or artwork's song, a voice model's name. */
  target_label: string | null
  reason: string | null
  details: Record<string, unknown>
  created_at: string
}

export type ClipAction = "approve" | "remove" | "flag"
export type ContentAction = "approve" | "unpublish" | "restore" | "drop"
export type TargetAction = ClipAction | ContentAction
export type UserAction = "warn" | "ban"
export type QueueTargetRef = { type: QueueTarget; id: string }

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

/** One page of a server-paged list (#540); a null cursor means it was the last. */
export type Page<T> = { items: T[]; next_cursor: string | null }

export type QueueQuery = {
  sort: QueueSort
  source: SourceFilter
  category: CategoryFilter
  cursor?: string | null
}

export function fetchModerationQueue(
  token: string,
  { cursor, ...query }: QueueQuery = {
    sort: "reports",
    source: "all",
    category: "all",
  }
): Promise<Page<QueueItem>> {
  const params = new URLSearchParams(query)
  if (cursor) params.set("cursor", cursor)
  return request<Page<QueueItem>>(`queue?${params}`, token)
}

export async function fetchModerationLog(
  token: string,
  cursor?: string | null
): Promise<Page<ModerationLogEntry>> {
  const params = new URLSearchParams({ limit: "100" })
  if (cursor) params.set("cursor", cursor)
  const page = await request<{
    entries: ModerationLogEntry[]
    next_cursor: string | null
  }>(`log?${params}`, token)
  return { items: page.entries, next_cursor: page.next_cursor }
}

function withReason(body: Record<string, unknown>, reason?: string) {
  const trimmed = reason?.trim()
  return trimmed ? { ...body, reason: trimmed } : body
}

type RawResult = { ok: boolean; detail?: string | null }

/** The backend rejects (422) a batch of more than this many ids. */
export const MAX_BATCH = 100

// "Select all" covers every loaded page of the queue, so large selections go out as
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

async function applyContentAction(
  token: string,
  targetType: ContentType,
  action: ContentAction,
  ids: string[],
  reason?: string
): Promise<ActionResult[]> {
  return inBatches(ids, async (batch) => {
    const { results } = await request<{
      results: (RawResult & { id: string })[]
    }>(
      "content",
      token,
      withReason({ target_type: targetType, action, ids: batch }, reason)
    )
    return results.map((r) => ({
      id: r.id,
      ok: r.ok,
      detail: r.detail ?? null,
    }))
  })
}

const QUEUE_TARGETS: QueueTarget[] = ["clip", "video", "artwork", "voice_model"]

/** Acts on a mixed selection: one request per target type, results in type order. */
export async function applyQueueAction(
  token: string,
  action: TargetAction,
  targets: QueueTargetRef[],
  reason?: string
): Promise<ActionResult[]> {
  const results: ActionResult[] = []
  for (const type of QUEUE_TARGETS) {
    const ids = targets.filter((t) => t.type === type).map((t) => t.id)
    if (ids.length === 0) continue
    results.push(
      ...(type === "clip"
        ? await applyClipAction(token, action as ClipAction, ids, reason)
        : await applyContentAction(
            token,
            type,
            action as ContentAction,
            ids,
            reason
          ))
    )
  }
  return results
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

/** An appeal as it appears in the admin queue (US-27.4): AppealView + clip/creator context. */
export type AppealQueueItem = AppealView & {
  clip_title: string | null
  clip_deleted: boolean
  creator_id: string
  creator_name: string | null
  action_reason: string | null
  action_at: string | null
  /** A newer moderation decision replaced the appealed one (#543); it can only be upheld. */
  superseded: boolean
}

export type AppealStatusFilter = "open" | "all"
export type AppealDecision = "uphold" | "reverse" | "request_info"

export async function fetchAppeals(
  token: string,
  status: AppealStatusFilter = "open",
  cursor?: string | null
): Promise<Page<AppealQueueItem>> {
  const params = new URLSearchParams({ status })
  if (cursor) params.set("cursor", cursor)
  const page = await request<{
    appeals: AppealQueueItem[]
    next_cursor: string | null
  }>(`appeals?${params}`, token)
  return { items: page.appeals, next_cursor: page.next_cursor }
}

export async function decideAppeal(
  token: string,
  appealId: string,
  decision: AppealDecision,
  note?: string
): Promise<AppealView> {
  const trimmed = note?.trim()
  return request<AppealView>(
    `appeals/${encodeURIComponent(appealId)}`,
    token,
    trimmed ? { decision, note: trimmed } : { decision }
  )
}

export const TARGET_LABELS: Record<QueueTarget, string> = {
  clip: "Clip",
  video: "Video",
  artwork: "Artwork",
  voice_model: "Voice model",
}

const TARGET_VERBS: Record<string, string> = {
  approve: "Approved",
  remove: "Removed",
  flag: "Flagged",
  unpublish: "Unpublished",
  restore: "Restored",
  drop: "Dropped",
}

const LOG_ACTION_LABELS: Record<string, string> = {
  warn: "Warned user",
  ban: "Banned user",
  update_screening_rules: "Updated screening rules",
  appeal_upheld: "Upheld appeal",
  appeal_reversed: "Reversed appeal",
  appeal_info_requested: "Requested appeal info",
  // Platform-written outcomes of the SoundCloud un-share queue (#569).
  soundcloud_unshared: "SoundCloud track made private",
  soundcloud_unshare_failed: "SoundCloud un-share failed, retrying",
  soundcloud_unshare_abandoned:
    "SoundCloud un-share abandoned: account unlinked",
}

export function formatLogAction(action: string, targetType = "clip"): string {
  const verb = TARGET_VERBS[action]
  const target = TARGET_LABELS[targetType as QueueTarget]
  if (verb && target) return `${verb} ${target.toLowerCase()}`
  return LOG_ACTION_LABELS[action] ?? action.replaceAll("_", " ")
}

// The API serializes naive UTC datetimes (no offset); `new Date` would read those as local time.
export function parseApiTime(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`)
}
