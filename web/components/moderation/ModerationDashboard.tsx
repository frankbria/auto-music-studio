"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { AppealsPanel } from "@/components/moderation/AppealsPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { clipAudioUrl } from "@/lib/clips"
import {
  applyQueueAction,
  applyUserAction,
  fetchModerationLog,
  fetchModerationQueue,
  formatLogAction,
  TARGET_LABELS,
  type CategoryFilter,
  type Page,
  type QueueItem,
  type QueueSort,
  type QueueTarget,
  type QueueTargetRef,
  type SourceFilter,
  type TargetAction,
  type UserAction,
  parseApiTime,
} from "@/lib/moderation"
import { REPORT_CATEGORIES } from "@/lib/reports"
import { videoStreamUrl } from "@/lib/video"

// Admin moderation dashboard (US-27.3): the review queue (reported and
// auto-flagged clips, plus flagged videos, artwork and voice models since #539)
// with per-row and bulk actions, and the activity log. Remove, Unpublish, Drop,
// Warn and Ban go through a reason dialog; Approve and Flag are one click.
// After any action the queue and log are refetched rather than patched locally,
// so what the admin sees is always what the backend now holds. Both are paged by
// the server (#540): sort and filters change what the server returns, and Load
// more appends the page after the last row.

type Pending =
  | { kind: "target"; action: TargetAction; targets: QueueTargetRef[] }
  | { kind: "user"; action: UserAction; ids: string[] }

type Notice = { status: string | null; failures: string[] }

const VERBS: Record<TargetAction | UserAction, string> = {
  approve: "Approved",
  remove: "Removed",
  flag: "Flagged",
  unpublish: "Unpublished",
  drop: "Dropped",
  warn: "Warned",
  ban: "Banned",
}

const NOUNS: Record<QueueTarget, string> = {
  clip: "clip",
  video: "video",
  artwork: "artwork image",
  voice_model: "voice model",
}

// Actions that open the reason dialog before running. Warn has no side effect
// beyond the notice, but a notice with no reason tells the creator nothing.
const CONFIRMED: Partial<
  Record<
    TargetAction | UserAction,
    { verb: string; description: string; destructive: boolean }
  >
> = {
  remove: {
    verb: "Remove",
    description:
      "Removed clips are made private and cannot be published again. Their releases go private and their SoundCloud tracks are un-shared. Their creators are notified.",
    destructive: true,
  },
  unpublish: {
    verb: "Unpublish",
    description:
      "Unpublished videos come off their song pages and cannot be published again.",
    destructive: true,
  },
  drop: {
    verb: "Drop",
    description:
      "Dropped artwork is deleted, and taken off its song if it was the selected cover.",
    destructive: true,
  },
  warn: {
    verb: "Warn",
    description:
      "Each creator gets a warning notice that includes this reason.",
    destructive: false,
  },
  ban: {
    verb: "Ban",
    description:
      "Banned accounts are signed out, cannot sign back in, and their public clips, releases and SoundCloud tracks are taken down.",
    destructive: true,
  },
}

const CATEGORY_LABELS = Object.fromEntries(
  REPORT_CATEGORIES.map((c) => [c.value, c.label])
) as Record<string, string>

const SOURCE_LABELS = { report: "User report", automated: "Automated" }

const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"

function plural(n: number, noun: string) {
  return `${n} ${noun}${n === 1 ? "" : "s"}`
}

function countOf(pending: Pending) {
  return pending.kind === "user" ? pending.ids.length : pending.targets.length
}

function nounFor(pending: Pending) {
  if (pending.kind === "user") return "creator"
  const types = new Set(pending.targets.map((t) => t.type))
  return types.size === 1 ? NOUNS[[...types][0]] : "item"
}

function keyOf(item: QueueItem) {
  return `${item.target_type}:${item.target_id}`
}

function refOf(item: QueueItem): QueueTargetRef {
  return { type: item.target_type, id: item.target_id }
}

function formatTime(iso: string) {
  const date = parseApiTime(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}

function unique(ids: (string | null)[]): string[] {
  return [...new Set(ids.filter((id): id is string => !!id))]
}

type FetchPage<T> = (cursor: string | null) => Promise<Page<T>>

// A server-paged list: `reload` fetches the first page, `more` the next one (null
// on the last page). Rows belong to the fetcher that loaded them, so a new sort or
// filter shows as loading instead of leaving the old rows up (and selectable), and
// a response a newer request has superseded is dropped, so a Load more that lands
// after a filter change can't append to the new list.
function usePages<T>(fetchPage: FetchPage<T> | null) {
  const [loaded, setLoaded] = useState<{
    from: FetchPage<T>
    rows: T[]
    cursor: string | null
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  const load = useCallback(
    (after: string | null) => {
      if (!fetchPage) return Promise.resolve()
      const request = ++latest.current
      return fetchPage(after).then(
        (page) => {
          if (request !== latest.current) return
          setLoaded((prev) => ({
            from: fetchPage,
            rows: after && prev ? [...prev.rows, ...page.items] : page.items,
            cursor: page.next_cursor,
          }))
          setError(null)
        },
        (e: unknown) => {
          if (request === latest.current) setError(errorMessage(e))
        }
      )
    },
    [fetchPage]
  )

  // `reload` runs the newest `load`, not the one captured by the render that started
  // an action: a token rotation or query change mid-action mounts a new fetcher, and a
  // reload through the old one would supersede its request and strand the list loading.
  const latestLoad = useRef(load)
  useEffect(() => {
    latestLoad.current = load
    void load(null)
  }, [load])

  const current = loaded?.from === fetchPage ? loaded : null
  const cursor = current?.cursor
  return {
    rows: current?.rows ?? null,
    error,
    more: cursor ? () => void load(cursor) : null,
    reload: () => latestLoad.current(null),
  }
}

function clipLabel(item: QueueItem) {
  if (item.target_type === "clip" && item.clip_deleted) return "Clip deleted"
  if (item.clip_deleted) return item.title ?? "Song deleted"
  return item.title ?? "Untitled clip"
}

export function ModerationDashboard({
  accessToken,
}: {
  accessToken: string | null
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [sort, setSort] = useState<QueueSort>("reports")
  const [source, setSource] = useState<SourceFilter>("all")
  const [category, setCategory] = useState<CategoryFilter>("all")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [confirming, setConfirming] = useState<Pending | null>(null)
  const [reason, setReason] = useState("")

  const queue = usePages(
    useMemo(
      () =>
        accessToken
          ? (cursor: string | null) =>
              fetchModerationQueue(accessToken, {
                sort,
                source,
                category,
                cursor,
              })
          : null,
      [accessToken, sort, source, category]
    )
  )
  const log = usePages(
    useMemo(
      () =>
        accessToken
          ? (cursor: string | null) => fetchModerationLog(accessToken, cursor)
          : null,
      [accessToken]
    )
  )
  const items = queue.rows
  const filtered = source !== "all" || category !== "all"

  // Bulk actions only ever touch rows the admin can currently see.
  const chosen = (items ?? []).filter((i) => selected.has(keyOf(i)))
  const allChosen = !!items?.length && chosen.length === items.length

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(allChosen ? new Set() : new Set((items ?? []).map(keyOf)))
  }

  function describeTarget(kind: Pending["kind"], id: string) {
    const all = items ?? []
    if (kind === "target") {
      const hit = all.find((i) => i.target_id === id)
      return hit ? clipLabel(hit) : id
    }
    return all.find((i) => i.creator_id === id)?.creator_name ?? id
  }

  async function run(pending: Pending, why?: string) {
    if (!accessToken || countOf(pending) === 0) return
    setBusy(true)
    setNotice(null)
    try {
      const results =
        pending.kind === "target"
          ? await applyQueueAction(
              accessToken,
              pending.action,
              pending.targets,
              why
            )
          : await applyUserAction(accessToken, pending.action, pending.ids, why)
      const ok = results.filter((r) => r.ok).length
      setNotice({
        status: ok
          ? `${VERBS[pending.action]} ${plural(ok, nounFor(pending))}.`
          : null,
        // An ok result can still carry a detail: e.g. a removal whose SoundCloud track stayed shared.
        failures: results
          .filter((r) => !r.ok || r.detail)
          .map(
            (r) =>
              `${describeTarget(pending.kind, r.id)}: ${r.detail ?? "Failed."}`
          ),
      })
      setSelected(new Set())
    } catch (error) {
      setNotice({ status: null, failures: [errorMessage(error)] })
    }
    // Stay busy until the reload lands: a Load more clicked meanwhile would supersede
    // it and leave the pre-action rows up, still actionable. reload() never rejects.
    await Promise.all([queue.reload(), log.reload()])
    setBusy(false)
  }

  function request(pending: Pending) {
    if (CONFIRMED[pending.action]) {
      setReason("")
      setConfirming(pending)
    } else void run(pending)
  }

  function confirm() {
    if (!confirming) return
    const pending = confirming
    setConfirming(null)
    void run(pending, reason)
  }

  const copy = confirming ? CONFIRMED[confirming.action] : undefined

  const liveClips = chosen
    .filter((i) => i.target_type === "clip" && !i.clip_deleted)
    .map(refOf)
  const chosenOf = (type: QueueTarget) =>
    chosen.filter((i) => i.target_type === type).map(refOf)
  const videos = chosenOf("video")
  const artwork = chosenOf("artwork")
  const creatorIds = unique(chosen.map((i) => i.creator_id))
  const bannableIds = unique(
    chosen.filter((i) => !i.creator_banned).map((i) => i.creator_id)
  )

  return (
    <div className="flex flex-col gap-4" data-slot="moderation-dashboard">
      {notice?.status && (
        <p role="status" className="text-sm">
          {notice.status}
        </p>
      )}
      {notice && notice.failures.length > 0 && (
        <div role="alert" className="text-sm text-destructive">
          <ul className="list-disc pl-5">
            {notice.failures.map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
        </div>
      )}

      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">Queue</TabsTrigger>
          <TabsTrigger value="appeals">Appeals</TabsTrigger>
          <TabsTrigger value="log">Activity log</TabsTrigger>
        </TabsList>

        <TabsContent value="queue" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="moderation-sort">Sort by</Label>
              <select
                id="moderation-sort"
                className={selectClass}
                disabled={busy}
                value={sort}
                onChange={(e) => setSort(e.target.value as QueueSort)}
              >
                <option value="reports">Report count</option>
                <option value="severity">Severity</option>
                <option value="newest">Newest</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="moderation-source">Source</Label>
              <select
                id="moderation-source"
                className={selectClass}
                disabled={busy}
                value={source}
                onChange={(e) => setSource(e.target.value as SourceFilter)}
              >
                <option value="all">All sources</option>
                <option value="report">User reports</option>
                <option value="automated">Automated flags</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="moderation-category">Category</Label>
              <select
                id="moderation-category"
                className={selectClass}
                disabled={busy}
                value={category}
                onChange={(e) => setCategory(e.target.value as CategoryFilter)}
              >
                <option value="all">All categories</option>
                {REPORT_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {chosen.length > 0 && (
            <div
              role="toolbar"
              aria-label="Bulk actions"
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2"
            >
              <span className="px-1 text-sm font-medium">
                {chosen.length} selected
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  request({
                    kind: "target",
                    action: "approve",
                    targets: chosen.map(refOf),
                  })
                }
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy || liveClips.length === 0}
                onClick={() =>
                  request({
                    kind: "target",
                    action: "remove",
                    targets: liveClips,
                  })
                }
              >
                Remove
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy || liveClips.length === 0}
                onClick={() =>
                  request({
                    kind: "target",
                    action: "flag",
                    targets: liveClips,
                  })
                }
              >
                Flag
              </Button>
              {videos.length > 0 && (
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    request({
                      kind: "target",
                      action: "unpublish",
                      targets: videos,
                    })
                  }
                >
                  Unpublish videos
                </Button>
              )}
              {artwork.length > 0 && (
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    request({
                      kind: "target",
                      action: "drop",
                      targets: artwork,
                    })
                  }
                >
                  Drop artwork
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                disabled={busy || creatorIds.length === 0}
                onClick={() =>
                  request({ kind: "user", action: "warn", ids: creatorIds })
                }
              >
                Warn creators
              </Button>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy || bannableIds.length === 0}
                onClick={() =>
                  request({ kind: "user", action: "ban", ids: bannableIds })
                }
              >
                Ban creators
              </Button>
            </div>
          )}

          {queue.error && (
            <p role="alert" className="text-sm text-destructive">
              {queue.error}
            </p>
          )}
          {items === null ? (
            !queue.error && (
              <p className="text-sm text-muted-foreground">Loading queue...</p>
            )
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {filtered
                ? "Nothing matches these filters."
                : "Nothing to review."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pr-2 pb-2 font-medium">
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={allChosen}
                        onChange={toggleAll}
                        className="size-4 accent-primary"
                      />
                    </th>
                    <th className="pr-3 pb-2 font-medium">Content</th>
                    <th className="pr-3 pb-2 font-medium">Type</th>
                    <th className="pr-3 pb-2 font-medium">Creator</th>
                    <th className="pr-3 pb-2 font-medium">Reports</th>
                    <th className="pr-3 pb-2 font-medium">Source</th>
                    <th className="pr-3 pb-2 font-medium">Preview</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <QueueRow
                      key={keyOf(item)}
                      item={item}
                      checked={selected.has(keyOf(item))}
                      busy={busy}
                      onToggle={() => toggle(keyOf(item))}
                      onTargetAction={(action) =>
                        request({
                          kind: "target",
                          action,
                          targets: [refOf(item)],
                        })
                      }
                      onUserAction={(action) =>
                        item.creator_id &&
                        request({
                          kind: "user",
                          action,
                          ids: [item.creator_id],
                        })
                      }
                    />
                  ))}
                </tbody>
              </table>
              <LoadMore onClick={queue.more} disabled={busy} />
            </div>
          )}
        </TabsContent>

        <TabsContent value="appeals">
          <AppealsPanel accessToken={accessToken} />
        </TabsContent>

        <TabsContent value="log">
          {log.error && (
            <p role="alert" className="text-sm text-destructive">
              {log.error}
            </p>
          )}
          {log.rows === null ? (
            !log.error && (
              <p className="text-sm text-muted-foreground">Loading log...</p>
            )
          ) : log.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No moderation actions yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pr-3 pb-2 font-medium">Time</th>
                    <th className="pr-3 pb-2 font-medium">Action</th>
                    <th className="pr-3 pb-2 font-medium">Target</th>
                    <th className="pr-3 pb-2 font-medium">Admin</th>
                    <th className="pb-2 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {log.rows.map((entry) => (
                    <tr key={entry.id} className="border-t border-border">
                      <td className="py-2 pr-3 whitespace-nowrap">
                        {formatTime(entry.created_at)}
                      </td>
                      <td className="py-2 pr-3">
                        {formatLogAction(entry.action, entry.target_type)}
                      </td>
                      <td className="py-2 pr-3">
                        {entry.target_label ?? (
                          <span className="font-mono text-xs">
                            {entry.target_type} {entry.target_id}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {entry.actor_name ?? (
                          <span className="font-mono text-xs">
                            {entry.actor_id ?? "system"}
                          </span>
                        )}
                      </td>
                      <td className="py-2">{entry.reason ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <LoadMore onClick={log.more} disabled={busy} />
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Dialog
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) setConfirming(null)
        }}
      >
        <DialogContent>
          {confirming && copy && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {copy.verb} {plural(countOf(confirming), nounFor(confirming))}
                  ?
                </DialogTitle>
                <DialogDescription>{copy.description}</DialogDescription>
              </DialogHeader>
              <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                  e.preventDefault()
                  confirm()
                }}
              >
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="moderation-reason">Reason (optional)</Label>
                  <Textarea
                    id="moderation-reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={1000}
                    rows={3}
                  />
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setConfirming(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    variant={copy.destructive ? "destructive" : "default"}
                  >
                    {copy.verb}
                  </Button>
                </DialogFooter>
              </form>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function LoadMore({
  onClick,
  disabled,
}: {
  onClick: (() => void) | null
  disabled: boolean
}) {
  if (!onClick) return null
  return (
    <Button
      size="sm"
      variant="outline"
      className="mt-3"
      disabled={disabled}
      onClick={onClick}
    >
      Load more
    </Button>
  )
}

function QueueRow({
  item,
  checked,
  busy,
  onToggle,
  onTargetAction,
  onUserAction,
}: {
  item: QueueItem
  checked: boolean
  busy: boolean
  onToggle: () => void
  onTargetAction: (action: TargetAction) => void
  onUserAction: (action: UserAction) => void
}) {
  const isClip = item.target_type === "clip"
  const label = clipLabel(item)
  const categories = Object.entries(item.categories).filter(
    ([, count]) => (count ?? 0) > 0
  )
  return (
    <tr className="border-t border-border align-top">
      <td className="py-2 pr-2">
        <input
          type="checkbox"
          aria-label={`Select ${label}`}
          checked={checked}
          onChange={onToggle}
          className="size-4 accent-primary"
        />
      </td>
      <td className="py-2 pr-3">
        <div className="flex flex-col gap-1">
          <span
            className={
              item.clip_deleted ? "text-muted-foreground italic" : "font-medium"
            }
          >
            {label}
          </span>
          <div className="flex flex-wrap gap-1">
            {item.content_warning && (
              <Badge variant="destructive">Content warning</Badge>
            )}
            {item.style_tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
          {item.description && (
            <span className="text-xs text-muted-foreground">
              {item.description}
            </span>
          )}
          {item.visibility && (
            <span className="text-xs text-muted-foreground">
              {item.visibility}
            </span>
          )}
          {item.published != null && (
            <span className="text-xs text-muted-foreground">
              {item.published ? "published" : "unpublished"}
            </span>
          )}
        </div>
      </td>
      <td className="py-2 pr-3">
        <Badge variant="outline">{TARGET_LABELS[item.target_type]}</Badge>
      </td>
      <td className="py-2 pr-3">
        <div className="flex flex-col items-start gap-1">
          <span>{item.creator_name ?? "-"}</span>
          {item.creator_banned && <Badge variant="destructive">Banned</Badge>}
        </div>
      </td>
      <td className="py-2 pr-3">
        <div className="flex flex-col items-start gap-1">
          <span className="font-medium tabular-nums">{item.report_count}</span>
          <div className="flex flex-wrap gap-1">
            {categories.map(([cat, count]) => (
              <Badge key={cat} variant="secondary">
                {CATEGORY_LABELS[cat] ?? cat} ({count})
              </Badge>
            ))}
          </div>
          <span className="text-xs whitespace-nowrap text-muted-foreground">
            {formatTime(item.latest_at)}
          </span>
        </div>
      </td>
      <td className="py-2 pr-3">
        <div className="flex flex-col items-start gap-1">
          {item.sources.map((s) => (
            <Badge key={s} variant="outline">
              {SOURCE_LABELS[s]}
            </Badge>
          ))}
          {item.moderation_flags.map((flag) => (
            <span
              key={flag}
              className="font-mono text-xs text-muted-foreground"
            >
              {flag}
            </span>
          ))}
        </div>
      </td>
      <td className="py-2 pr-3">
        {isClip && item.clip_id && !item.clip_deleted && (
          <audio
            controls
            preload="none"
            src={clipAudioUrl(item.clip_id)}
            aria-label={`Play ${label}`}
            className="h-8 w-48"
          />
        )}
        {item.target_type === "video" && (
          <video
            controls
            preload="none"
            src={videoStreamUrl(item.target_id)}
            aria-label={`Play video for ${label}`}
            className="h-24 w-40"
          />
        )}
      </td>
      <td className="py-2">
        <div className="flex flex-wrap gap-1">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onTargetAction("approve")}
          >
            Approve
          </Button>
          {isClip && !item.clip_deleted && (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => onTargetAction("remove")}
              >
                Remove
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onTargetAction("flag")}
              >
                Flag
              </Button>
            </>
          )}
          {item.target_type === "video" && (
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => onTargetAction("unpublish")}
            >
              Unpublish
            </Button>
          )}
          {item.target_type === "artwork" && (
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => onTargetAction("drop")}
            >
              Drop
            </Button>
          )}
          {item.creator_id && (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onUserAction("warn")}
              >
                Warn creator
              </Button>
              {!item.creator_banned && (
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() => onUserAction("ban")}
                >
                  Ban creator
                </Button>
              )}
            </>
          )}
        </div>
      </td>
    </tr>
  )
}
