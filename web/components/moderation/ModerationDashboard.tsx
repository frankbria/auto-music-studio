"use client"

import { useCallback, useEffect, useMemo, useState } from "react"

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
  applyClipAction,
  applyUserAction,
  fetchModerationLog,
  fetchModerationQueue,
  filterQueue,
  formatLogAction,
  sortQueue,
  type CategoryFilter,
  type ClipAction,
  type ModerationLogEntry,
  type QueueItem,
  type QueueSort,
  type SourceFilter,
  type UserAction,
  parseApiTime,
} from "@/lib/moderation"
import { REPORT_CATEGORIES } from "@/lib/reports"

// Admin moderation dashboard (US-27.3): the review queue (reported and
// auto-flagged clips) with per-row and bulk actions, and the activity log.
// Remove, Warn and Ban go through a reason dialog; Approve and Flag are one click.
// After any action the queue and log are refetched rather than patched locally,
// so what the admin sees is always what the backend now holds.

type Pending =
  | { kind: "clip"; action: ClipAction; ids: string[] }
  | { kind: "user"; action: UserAction; ids: string[] }

type Notice = { status: string | null; failures: string[] }

const VERBS: Record<ClipAction | UserAction, string> = {
  approve: "Approved",
  remove: "Removed",
  flag: "Flagged",
  warn: "Warned",
  ban: "Banned",
}

// Actions that open the reason dialog before running. Warn has no side effect
// beyond the notice, but a notice with no reason tells the creator nothing.
const CONFIRMED: Partial<
  Record<
    ClipAction | UserAction,
    { verb: string; description: string; destructive: boolean }
  >
> = {
  remove: {
    verb: "Remove",
    description:
      "Removed clips are made private and cannot be published again. Their creators are notified.",
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
      "Banned accounts are signed out, cannot sign back in, and their public clips are taken down.",
    destructive: true,
  },
}

const CATEGORY_LABELS = Object.fromEntries(
  REPORT_CATEGORIES.map((c) => [c.value, c.label])
) as Record<string, string>

const SOURCE_LABELS = { report: "User report", automated: "Automated" }

const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"

function plural(n: number, noun: string) {
  return `${n} ${noun}${n === 1 ? "" : "s"}`
}

function nounFor(kind: Pending["kind"]) {
  return kind === "clip" ? "clip" : "creator"
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

function load(token: string) {
  return Promise.allSettled([
    fetchModerationQueue(token),
    fetchModerationLog(token),
  ] as const)
}

type Loaded = Awaited<ReturnType<typeof load>>

function clipLabel(item: QueueItem) {
  if (item.clip_deleted) return "Clip deleted"
  return item.title ?? "Untitled clip"
}

export function ModerationDashboard({
  accessToken,
}: {
  accessToken: string | null
}) {
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [log, setLog] = useState<ModerationLogEntry[] | null>(null)
  const [logError, setLogError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [sort, setSort] = useState<QueueSort>("reports")
  const [source, setSource] = useState<SourceFilter>("all")
  const [category, setCategory] = useState<CategoryFilter>("all")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [confirming, setConfirming] = useState<Pending | null>(null)
  const [reason, setReason] = useState("")

  const apply = useCallback((loaded: Loaded) => {
    const [queue, entries] = loaded
    if (queue.status === "fulfilled") {
      setItems(queue.value)
      setLoadError(null)
    } else setLoadError(errorMessage(queue.reason))
    if (entries.status === "fulfilled") {
      setLog(entries.value)
      setLogError(null)
    } else setLogError(errorMessage(entries.reason))
  }, [])

  useEffect(() => {
    if (!accessToken) return
    let active = true
    void load(accessToken).then((loaded) => {
      if (active) apply(loaded)
    })
    return () => {
      active = false
    }
  }, [accessToken, apply])

  const visible = useMemo(
    () => sortQueue(filterQueue(items ?? [], source, category), sort),
    [items, source, category, sort]
  )
  // Bulk actions only ever touch rows the admin can currently see.
  const chosen = visible.filter((i) => selected.has(i.clip_id))
  const allChosen = visible.length > 0 && chosen.length === visible.length

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(allChosen ? new Set() : new Set(visible.map((i) => i.clip_id)))
  }

  function describeTarget(kind: Pending["kind"], id: string) {
    const all = items ?? []
    if (kind === "clip") {
      const hit = all.find((i) => i.clip_id === id)
      return hit ? clipLabel(hit) : id
    }
    return all.find((i) => i.creator_id === id)?.creator_name ?? id
  }

  async function run(pending: Pending, why?: string) {
    if (!accessToken || pending.ids.length === 0) return
    setBusy(true)
    setNotice(null)
    try {
      const results =
        pending.kind === "clip"
          ? await applyClipAction(accessToken, pending.action, pending.ids, why)
          : await applyUserAction(accessToken, pending.action, pending.ids, why)
      const ok = results.filter((r) => r.ok).length
      setNotice({
        status: ok
          ? `${VERBS[pending.action]} ${plural(ok, nounFor(pending.kind))}.`
          : null,
        failures: results
          .filter((r) => !r.ok)
          .map(
            (r) =>
              `${describeTarget(pending.kind, r.id)}: ${r.detail ?? "Failed."}`
          ),
      })
      setSelected(new Set())
    } catch (error) {
      setNotice({ status: null, failures: [errorMessage(error)] })
    } finally {
      setBusy(false)
    }
    apply(await load(accessToken))
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

  const liveIds = chosen.filter((i) => !i.clip_deleted).map((i) => i.clip_id)
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
          <TabsTrigger value="log">Activity log</TabsTrigger>
        </TabsList>

        <TabsContent value="queue" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="moderation-sort">Sort by</Label>
              <select
                id="moderation-sort"
                className={selectClass}
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
                    kind: "clip",
                    action: "approve",
                    ids: chosen.map((i) => i.clip_id),
                  })
                }
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy || liveIds.length === 0}
                onClick={() =>
                  request({ kind: "clip", action: "remove", ids: liveIds })
                }
              >
                Remove
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy || liveIds.length === 0}
                onClick={() =>
                  request({ kind: "clip", action: "flag", ids: liveIds })
                }
              >
                Flag
              </Button>
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

          {loadError ? (
            <p role="alert" className="text-sm text-destructive">
              {loadError}
            </p>
          ) : items === null ? (
            <p className="text-sm text-muted-foreground">Loading queue...</p>
          ) : visible.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {items.length === 0
                ? "Nothing to review."
                : "No clips match these filters."}
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
                    <th className="pr-3 pb-2 font-medium">Clip</th>
                    <th className="pr-3 pb-2 font-medium">Creator</th>
                    <th className="pr-3 pb-2 font-medium">Reports</th>
                    <th className="pr-3 pb-2 font-medium">Source</th>
                    <th className="pr-3 pb-2 font-medium">Listen</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((item) => (
                    <QueueRow
                      key={item.clip_id}
                      item={item}
                      checked={selected.has(item.clip_id)}
                      busy={busy}
                      onToggle={() => toggle(item.clip_id)}
                      onClipAction={(action) =>
                        request({ kind: "clip", action, ids: [item.clip_id] })
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
            </div>
          )}
        </TabsContent>

        <TabsContent value="log">
          {logError ? (
            <p role="alert" className="text-sm text-destructive">
              {logError}
            </p>
          ) : log === null ? (
            <p className="text-sm text-muted-foreground">Loading log...</p>
          ) : log.length === 0 ? (
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
                  {log.map((entry) => (
                    <tr key={entry.id} className="border-t border-border">
                      <td className="py-2 pr-3 whitespace-nowrap">
                        {formatTime(entry.created_at)}
                      </td>
                      <td className="py-2 pr-3">
                        {formatLogAction(entry.action)}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">
                        {entry.target_type} {entry.target_id}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">
                        {entry.actor_id}
                      </td>
                      <td className="py-2">{entry.reason ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                  {copy.verb}{" "}
                  {plural(confirming.ids.length, nounFor(confirming.kind))}?
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

function QueueRow({
  item,
  checked,
  busy,
  onToggle,
  onClipAction,
  onUserAction,
}: {
  item: QueueItem
  checked: boolean
  busy: boolean
  onToggle: () => void
  onClipAction: (action: ClipAction) => void
  onUserAction: (action: UserAction) => void
}) {
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
          {item.visibility && (
            <span className="text-xs text-muted-foreground">
              {item.visibility}
            </span>
          )}
        </div>
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
        {!item.clip_deleted && (
          <audio
            controls
            preload="none"
            src={clipAudioUrl(item.clip_id)}
            aria-label={`Play ${label}`}
            className="h-8 w-48"
          />
        )}
      </td>
      <td className="py-2">
        <div className="flex flex-wrap gap-1">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onClipAction("approve")}
          >
            Approve
          </Button>
          {!item.clip_deleted && (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => onClipAction("remove")}
              >
                Remove
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onClipAction("flag")}
              >
                Flag
              </Button>
            </>
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
