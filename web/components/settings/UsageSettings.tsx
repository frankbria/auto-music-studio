"use client"

import { useEffect, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Download01Icon, Loading03Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { formatCredits } from "@/lib/credits"
import {
  downloadUsageCsv,
  fetchUsage,
  formatCategory,
  type UsageSummary,
} from "@/lib/usage"

// US-26.5: the usage dashboard. Split from the route component so it can be rendered in
// a test without the App Router, like BillingSettings next door.
//
// The charts are hand-drawn SVG rather than a charting dependency: two bar charts on one
// page do not justify pulling recharts (and its React reconciler quirks) into a bundle
// that currently has no chart library at all. The same choice was made for the mastering
// EQ display.

const WINDOWS = [7, 30, 90]

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })
}

/** "monthly_reset" -> "Monthly reset". Good enough for every action type we ledger. */
function formatAction(actionType: string): string {
  const spaced = actionType.replaceAll("_", " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Bars for the daily series. Zero-credit days keep their slot so the axis stays honest. */
function DailyChart({ daily }: { daily: UsageSummary["daily"] }) {
  const peak = Math.max(...daily.map((point) => point.credits), 0)
  const width = Math.max(daily.length * 4, 4)

  return (
    <svg
      role="img"
      aria-label={`Credits used per day over the last ${daily.length} days`}
      viewBox={`0 0 ${width} 40`}
      preserveAspectRatio="none"
      className="h-32 w-full"
    >
      {daily.map((point, index) => {
        // A flat-zero window would divide by zero. A quiet day draws nothing at all —
        // a minimum-height bar would read as "a little was spent here".
        const scaled = peak > 0 ? (Math.max(point.credits, 0) / peak) * 38 : 0
        const height = point.credits > 0 ? Math.max(scaled, 0.5) : 0
        return (
          <rect
            key={point.date}
            x={index * 4}
            y={40 - height}
            width={3}
            height={height}
            rx={0.5}
            className="fill-primary"
          >
            <title>{`${point.date}: ${formatCredits(point.credits)} credits`}</title>
          </rect>
        )
      })}
    </svg>
  )
}

export function UsageSettings({ accessToken }: { accessToken: string | null }) {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!accessToken) return
    let active = true
    // State is set from the promise callbacks, not the effect body —
    // `react-hooks/set-state-in-effect` is an error in this repo.
    fetchUsage(accessToken, days)
      .then((result) => {
        if (!active) return
        setSummary(result)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!active) return
        setError(err instanceof Error ? err.message : "Could not load your usage.")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [accessToken, days])

  if (loading && !summary) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <HugeiconsIcon icon={Loading03Icon} size={16} className="animate-spin" />
        Loading usage…
      </p>
    )
  }

  if (!summary) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error ?? "Could not load your usage."}
      </p>
    )
  }

  const peakCategory = Math.max(
    ...summary.categories.map((row) => row.credits),
    0
  )

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Credits remaining
            <Badge variant={summary.tier === "pro" ? "default" : "outline"}>
              {summary.tier === "pro" ? "Pro" : "Free"}
            </Badge>
          </CardTitle>
          <CardDescription>
            {summary.days_until_reset === null
              ? "Your monthly allowance renews on your signup anniversary."
              : `Your monthly allowance renews in ${summary.days_until_reset} days.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <p className="text-4xl font-semibold tabular-nums">
            {formatCredits(summary.total_credits)}
          </p>
          <div className="flex flex-col gap-0.5 text-sm text-muted-foreground">
            <span>{formatCredits(summary.monthly_credits)} monthly</span>
            <span>{formatCredits(summary.purchased_credits)} purchased</span>
          </div>
          {summary.reset_at && (
            <p className="text-sm text-muted-foreground">
              Resets {formatDate(summary.reset_at)}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Credits used</CardTitle>
            <CardDescription>
              Daily consumption over the last {summary.window_days} days.
            </CardDescription>
          </div>
          <div className="flex gap-1">
            {WINDOWS.map((window) => (
              <Button
                key={window}
                size="sm"
                variant={days === window ? "default" : "outline"}
                onClick={() => setDays(window)}
              >
                {window} days
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <DailyChart daily={summary.daily} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>By category</CardTitle>
          <CardDescription>
            Where your credits went. Refunds are already netted off.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {summary.categories.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No credits used in the last {summary.window_days} days.
            </p>
          ) : (
            <ul data-testid="category-breakdown" className="flex flex-col gap-3">
              {summary.categories.map((row) => (
                <li key={row.category} className="flex flex-col gap-1">
                  <div className="flex justify-between text-sm">
                    <span>{formatCategory(row.category)}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {formatCredits(row.credits)} credits
                    </span>
                  </div>
                  <div
                    data-testid="category-bar"
                    className="h-2 rounded-full bg-primary"
                    style={{
                      // Clamped at zero: a refund whose charge fell outside the window
                      // nets negative, and a negative width is invalid CSS — the browser
                      // drops it and the bar renders full-width, the opposite of the truth.
                      width: `${peakCategory > 0 ? (Math.max(row.credits, 0) / peakCategory) * 100 : 0}%`,
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>History</CardTitle>
            <CardDescription>
              Every credit movement in the window, newest first.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={summary.history.length === 0}
            onClick={() => downloadUsageCsv(summary)}
          >
            <HugeiconsIcon icon={Download01Icon} size={16} />
            Export CSV
          </Button>
        </CardHeader>
        <CardContent>
          {summary.history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No activity yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Date</th>
                    <th className="pb-2 font-medium">Action</th>
                    <th className="pb-2 font-medium">Clip</th>
                    <th className="pb-2 font-medium">Credits</th>
                    <th className="pb-2 font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.history.map((row) => (
                    <tr
                      key={`${row.created_at}-${row.action_type}-${row.job_id}`}
                      className="border-t border-border"
                    >
                      <td className="py-2 whitespace-nowrap">
                        {formatDate(row.created_at)}
                      </td>
                      <td className="py-2">{formatAction(row.action_type)}</td>
                      <td className="py-2">{row.clip_title ?? "—"}</td>
                      <td className="py-2 whitespace-nowrap tabular-nums">
                        {/* Charges read as credits spent; anything that gave credit back
                            keeps its sign so a refund is not mistaken for a charge. */}
                        {row.amount > 0
                          ? `+${formatCredits(row.amount)}`
                          : formatCredits(-row.amount)}
                      </td>
                      <td className="py-2 whitespace-nowrap tabular-nums text-muted-foreground">
                        {formatCredits(row.balance_after)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
