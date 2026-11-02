"use client"

import { useEffect, useState, type ReactNode } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon, StarIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  fetchBillingHistory,
  fetchCreditPacks,
  fetchPlans,
  fetchSubscription,
  formatAmount,
  openPortal,
  startCheckout,
  startTopUp,
  type BillingHistoryEntry,
  type BillingInterval,
  type CreditPack,
  type Plan,
  type Subscription,
} from "@/lib/billing"
import {
  ENTERPRISE_FEATURES,
  FREE_FEATURES,
  PRO_BENEFITS,
  PRO_FEATURES,
  TIER_LABELS,
  toTier,
} from "@/lib/tiers"

// US-26.3: the billing page. `UpgradeModal` and the out-of-credits prompt have linked
// to /settings/billing since US-26.2, but the route did not exist — every one of those
// CTAs was a 404. This is the page they meant.
//
// Split from the route component so it can be rendered in a test without the App Router
// (the next/navigation mock in this repo has no useParams — see the settings page).

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

const FREE_MONTHLY_CREDITS = 50
const BILLING_INTERVALS: BillingInterval[] = ["month", "year"]
const INTERVAL_LABELS: Record<BillingInterval, string> = {
  month: "Monthly",
  year: "Annual",
}

function PlanPrice({
  plan,
  interval,
}: {
  plan: Plan
  interval: BillingInterval
}) {
  const price = plan.prices[interval]
  if (!plan.available[interval] || price === null) {
    return (
      <p className="text-sm text-muted-foreground">
        Not available {interval === "year" ? "annually" : "monthly"}
      </p>
    )
  }
  if (interval === "month") {
    return (
      <p className="text-lg font-semibold tabular-nums">
        {formatAmount(price, plan.currency)} / month
      </p>
    )
  }
  const monthly = plan.prices.month
  const discount = monthly ? Math.round((1 - price / (monthly * 12)) * 100) : 0
  return (
    <div>
      <p className="text-lg font-semibold tabular-nums">
        {formatAmount(price, plan.currency)} / year
      </p>
      <p className="text-xs text-muted-foreground tabular-nums">
        {formatAmount(price / 12, plan.currency)}/mo
        {discount > 0 && `, save ${discount}%`}
      </p>
    </div>
  )
}

function PlanTile({
  name,
  isCurrent,
  price,
  monthlyCredits,
  features,
  action,
}: {
  name: string
  isCurrent: boolean
  price: ReactNode
  monthlyCredits: number
  features: string[]
  action: ReactNode
}) {
  return (
    <section
      aria-label={`${name} plan`}
      data-current={isCurrent || undefined}
      className="flex flex-col gap-3 rounded-lg border border-border p-4 data-[current]:border-primary"
    >
      <h3 className="flex items-center gap-2 font-medium">
        {name}
        {isCurrent && <Badge>Current plan</Badge>}
      </h3>
      {price}
      <p className="text-sm">
        {monthlyCredits.toLocaleString()} credits / month
      </p>
      <ul className="flex flex-1 flex-col gap-1 text-sm text-muted-foreground">
        {features.map((feature) => (
          <li key={feature}>{feature}</li>
        ))}
      </ul>
      {action}
    </section>
  )
}

export function BillingSettings({
  accessToken,
}: {
  accessToken: string | null
}) {
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [history, setHistory] = useState<BillingHistoryEntry[]>([])
  const [packs, setPacks] = useState<CreditPack[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [billingInterval, setBillingInterval] =
    useState<BillingInterval>("month")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!accessToken) return
    let active = true
    // Both requests in flight together: the history is not needed to render the plan
    // card, but loading serially would paint the page twice. State is set from the
    // promise callbacks rather than the effect body — `react-hooks/set-state-in-effect`
    // is an error in this repo, and the same shape is used in use-subscription-tier.
    //
    // A failed history does not fail the page: not knowing past charges is a worse
    // reason to hide the upgrade button than showing an empty table.
    Promise.all([
      fetchSubscription(accessToken),
      fetchBillingHistory(accessToken).catch(() => [] as BillingHistoryEntry[]),
      fetchCreditPacks(accessToken).catch(() => [] as CreditPack[]),
      fetchPlans(accessToken).catch(() => [] as Plan[]),
    ])
      .then(([sub, entries, creditPacks, paidPlans]) => {
        if (!active) return
        setSubscription(sub)
        setHistory(entries)
        setPacks(creditPacks)
        setPlans(paidPlans)
      })
      .catch(() => {
        if (active) setError("Could not load your billing details.")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [accessToken])

  async function go(action: (token: string) => Promise<string>) {
    if (!accessToken) return
    setBusy(true)
    setError(null)
    try {
      window.location.href = await action(accessToken)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.")
      // Only cleared on failure: on success the browser is already navigating, and
      // re-enabling the button would invite a second checkout session.
      setBusy(false)
    }
  }

  const tier = toTier(subscription?.tier)
  const isPaid = tier !== "free"
  const tierLabel = TIER_LABELS[tier]
  const billingEnabled = subscription?.billing_enabled !== false
  const showPlans = billingEnabled && plans.length > 0
  const intervals = BILLING_INTERVALS.filter((i) =>
    plans.some((plan) => plan.available[i])
  )
  const activeInterval = intervals.includes(billingInterval)
    ? billingInterval
    : (intervals[0] ?? "month")

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <HugeiconsIcon
          icon={Loading03Icon}
          size={16}
          className="animate-spin"
        />
        Loading billing…
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Your plan
            <Badge variant={isPaid ? "default" : "outline"}>{tierLabel}</Badge>
          </CardTitle>
          <CardDescription>
            {isPaid
              ? subscription?.cancel_at_period_end
                ? // The single most important sentence on this page: someone who has
                  // cancelled needs to know they still have what they paid for.
                  `Cancelled — ${tierLabel} access continues until ${
                    subscription.current_period_end
                      ? formatDate(subscription.current_period_end)
                      : "the end of the billing period"
                  }.`
                : subscription?.status === "past_due"
                  ? `We could not take your last payment. We'll retry — update your card to avoid losing ${tierLabel}.`
                  : "Renews automatically."
              : "Upgrade to unlock everything Auto Music Studio can do."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!isPaid && !showPlans && (
            <ul className="flex flex-col gap-1.5 text-sm">
              {PRO_BENEFITS.map((benefit) => (
                <li key={benefit} className="flex items-start gap-2">
                  <span aria-hidden className="text-muted-foreground">
                    •
                  </span>
                  <span>{benefit}</span>
                </li>
              ))}
            </ul>
          )}

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}

          {!billingEnabled ? (
            <p className="text-sm text-muted-foreground">
              Billing is not configured on this deployment.
            </p>
          ) : isPaid ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => go(openPortal)}
            >
              Manage subscription
            </Button>
          ) : (
            !showPlans && (
              <Button
                disabled={busy}
                onClick={() =>
                  go((token) => startCheckout(token, "pro", "month"))
                }
              >
                <HugeiconsIcon icon={StarIcon} size={16} />
                {busy ? "Starting checkout…" : "Upgrade to Pro"}
              </Button>
            )
          )}
        </CardContent>
      </Card>

      {showPlans && (
        <Card>
          <CardHeader>
            <CardTitle>Plans</CardTitle>
            <CardDescription>
              {isPaid
                ? "To switch plans, use Manage subscription above."
                : "Pick the plan that fits how much you make."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {intervals.length > 1 && (
              <div
                role="group"
                aria-label="Billing interval"
                className="inline-flex w-fit gap-1 rounded-md border border-border p-0.5"
              >
                {intervals.map((option) => (
                  <Button
                    key={option}
                    size="sm"
                    variant={option === activeInterval ? "secondary" : "ghost"}
                    aria-pressed={option === activeInterval}
                    onClick={() => setBillingInterval(option)}
                  >
                    {INTERVAL_LABELS[option]}
                  </Button>
                ))}
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <PlanTile
                name={TIER_LABELS.free}
                isCurrent={tier === "free"}
                price={
                  <p className="text-lg font-semibold tabular-nums">
                    {formatAmount(0, "usd")}
                  </p>
                }
                monthlyCredits={FREE_MONTHLY_CREDITS}
                features={FREE_FEATURES}
                action={null}
              />
              {plans.map((plan) => (
                <PlanTile
                  key={plan.plan}
                  name={TIER_LABELS[plan.plan]}
                  isCurrent={tier === plan.plan}
                  price={<PlanPrice plan={plan} interval={activeInterval} />}
                  monthlyCredits={plan.monthly_credits}
                  features={
                    plan.plan === "enterprise"
                      ? ENTERPRISE_FEATURES
                      : PRO_FEATURES
                  }
                  action={
                    !isPaid &&
                    plan.available[activeInterval] && (
                      <Button
                        disabled={busy}
                        onClick={() =>
                          go((token) =>
                            startCheckout(token, plan.plan, activeInterval)
                          )
                        }
                      >
                        <HugeiconsIcon icon={StarIcon} size={16} />
                        Upgrade to {TIER_LABELS[plan.plan]}
                      </Button>
                    )
                  }
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* US-26.4: top-ups are available on every tier, so this sits outside the
          free-tier branch. A Pro musician who burns 500 credits mid-project needs it
          more than a free user does. */}
      {packs.length > 0 && billingEnabled && (
        <Card>
          <CardHeader>
            <CardTitle>Buy credits</CardTitle>
            <CardDescription>
              One-off packs. Purchased credits never expire, and they are spent
              only after your monthly allowance runs out.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            {packs.map((pack) => (
              <Button
                key={pack.id}
                variant="outline"
                disabled={busy}
                onClick={() => go((token) => startTopUp(token, pack.id))}
                className="h-auto flex-col items-start gap-0.5 py-3"
              >
                <span className="font-medium">{pack.credits} credits</span>
                <span className="text-xs text-muted-foreground">
                  {formatAmount(pack.price, pack.currency)}
                </span>
              </Button>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Billing history</CardTitle>
          <CardDescription>Your past charges.</CardDescription>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No charges yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Date</th>
                    <th className="pb-2 font-medium">Description</th>
                    <th className="pb-2 font-medium">Amount</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {history.map((entry) => (
                    <tr key={entry.id} className="border-t border-border">
                      <td className="py-2 whitespace-nowrap">
                        {formatDate(entry.created_at)}
                      </td>
                      <td className="py-2">
                        {entry.description ?? entry.event_type}
                      </td>
                      <td className="py-2 whitespace-nowrap tabular-nums">
                        {formatAmount(entry.amount, entry.currency)}
                      </td>
                      <td className="py-2">{entry.status ?? "—"}</td>
                      <td className="py-2 text-right">
                        {entry.invoice_url && (
                          <a
                            href={entry.invoice_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary underline-offset-4 hover:underline"
                          >
                            Invoice
                          </a>
                        )}
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
