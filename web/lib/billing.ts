// Billing API client (US-26.3). Thin wrappers over the same-origin proxy in
// app/api/billing, kept out of the page so the page stays about rendering.

export type Subscription = {
  tier: string
  status: string | null
  current_period_end: string | null
  cancel_at_period_end: boolean
  /** False on a deployment with no Stripe configured — hide the upgrade CTA. */
  billing_enabled: boolean
}

export type BillingHistoryEntry = {
  id: string
  event_type: string
  /** Major units (dollars), already divided by the API. Null for non-charge events. */
  amount: number | null
  currency: string | null
  status: string | null
  description: string | null
  invoice_url: string | null
  created_at: string
}

function authHeaders(token: string): HeadersInit {
  return { authorization: `Bearer ${token}` }
}

export async function fetchSubscription(token: string): Promise<Subscription> {
  const res = await fetch("/api/billing/subscription", {
    headers: authHeaders(token),
    signal: AbortSignal.timeout(8000),
  })
  if (!res.ok) throw new Error("Could not load your subscription.")
  return res.json()
}

export async function fetchBillingHistory(
  token: string
): Promise<BillingHistoryEntry[]> {
  const res = await fetch("/api/billing/history", {
    headers: authHeaders(token),
    signal: AbortSignal.timeout(8000),
  })
  if (!res.ok) throw new Error("Could not load your billing history.")
  const body = (await res.json()) as { entries?: BillingHistoryEntry[] }
  return body.entries ?? []
}

/**
 * Start checkout or open the billing portal, returning the URL to navigate to.
 *
 * The caller navigates rather than this doing it, so a failure surfaces as an error
 * message on the page instead of a blank tab.
 */
async function redirectUrl(
  path: "checkout" | "portal",
  token: string
): Promise<string> {
  const res = await fetch(`/api/billing/${path}`, {
    method: "POST",
    headers: authHeaders(token),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(
      body.detail ||
        (res.status === 503
          ? "Billing is not configured on this deployment."
          : "Something went wrong. Please try again.")
    )
  }
  if (!body.url) throw new Error("No checkout URL was returned.")
  return body.url as string
}

export const startCheckout = (token: string) => redirectUrl("checkout", token)
export const openPortal = (token: string) => redirectUrl("portal", token)

/** "$12.00" — Intl handles the currency symbol so this never hardcodes a locale. */
export function formatAmount(
  amount: number | null,
  currency: string | null
): string {
  if (amount === null) return "—"
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: (currency || "usd").toUpperCase(),
  }).format(amount)
}
