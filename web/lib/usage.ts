/**
 * Usage dashboard client (US-26.5).
 *
 * One read of `/api/credits/usage` backs the whole page — balance, chart, breakdown and
 * history are three views of the same ledger window, so fetching them apart would let
 * them disagree mid-render. The CSV is built here from that same payload rather than by
 * a second endpoint: the data is already in the browser, and a download that re-queries
 * can export something the musician never saw.
 */

import { CreditsError } from "@/lib/credits"

export type UsageRow = {
  created_at: string
  action_type: string
  category: string
  /** Signed as the ledger stores it: negative is a charge, positive a refund or grant. */
  amount: number
  balance_after: number
  job_id: string
  clip_title: string | null
}

export type UsageSummary = {
  tier: string
  monthly_credits: number
  purchased_credits: number
  total_credits: number
  reset_at: string | null
  days_until_reset: number | null
  window_days: number
  daily: { date: string; credits: number }[]
  categories: { category: string; credits: number }[]
  history: UsageRow[]
}

const CATEGORY_LABELS: Record<string, string> = {
  generation: "Generation",
  editing: "Editing",
  mastering: "Mastering",
  video: "Video",
  extraction: "Stems & MIDI",
  voice: "Voice training",
  grant: "Monthly credits",
  other: "Other",
}

/** Human label for a category, falling back to the raw value for anything new. */
export function formatCategory(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

/** The caller's usage over the last `days`. Throws CreditsError on failure. */
export async function fetchUsage(
  token: string,
  days = 30
): Promise<UsageSummary> {
  const res = await fetch(`/api/credits/usage?days=${days}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  const body = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new CreditsError(
      typeof body?.detail === "string"
        ? body.detail
        : "Could not load your usage.",
      res.status
    )
  }

  // The dashboard maps over every array in here. A truncated or unparseable payload that
  // still came back 200 should surface as an error, not as a blank page from a crash.
  if (!Array.isArray(body?.daily) || !Array.isArray(body?.history)) {
    throw new CreditsError("Could not load your usage.", res.status)
  }
  return body as UsageSummary
}

// `credits_used`, not `credits`: the column is signed as *spent*, so a refund is negative
// and the column sums to the net spend a spreadsheet is opened to compute. That is the
// opposite sign from the on-screen table, which shows a refund as `+4` because there the
// question is "what happened to my balance". The header names the convention rather than
// leaving the reader to infer it from a row.
const CSV_HEADER = "date,action,category,clip,credits_used,balance_after"

function csvCell(value: string | number | null): string {
  if (value === null) return ""
  // Numbers go out bare — a refund's leading `-` is arithmetic, not an escape problem.
  if (typeof value === "number") return String(value)

  // Excel evaluates a cell opening with = + - @ as a formula, and clip titles are
  // user-controlled text landing in a file the musician will double-click.
  const text = /^[=+\-@]/.test(value) ? `'${value}` : value

  // Quote only when it would otherwise break the row — a clip titled `Hey, "You"` shifts
  // every later column if it goes out bare.
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

/** The usage history as CSV, credits signed as *spent* (a refund is negative). */
export function buildUsageCsv(summary: UsageSummary): string {
  const rows = summary.history.map((row) =>
    [
      row.created_at,
      row.action_type,
      row.category,
      row.clip_title,
      -row.amount,
      row.balance_after,
    ]
      .map(csvCell)
      .join(",")
  )
  return [CSV_HEADER, ...rows].join("\n") + "\n"
}

/** Save the usage history as a CSV file, using the repo's blob/anchor download idiom. */
export function downloadUsageCsv(summary: UsageSummary): void {
  const blob = new Blob([buildUsageCsv(summary)], {
    type: "text/csv;charset=utf-8",
  })
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `usage-last-${summary.window_days}-days.csv`
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
