/**
 * Credit balance client (US-26.1).
 *
 * Talks to the same-origin BFF proxy under `/api/credits`, which forwards the bearer
 * token so the backend URL stays server-side.
 */

/** What the sidebar needs to show, plus where to send someone who has run out. */
export type CreditBalance = {
  balance: number
  tier: string
  upgrade_url: string
}

/**
 * The shape every billed endpoint returns with 402.
 *
 * `message` and `upgrade_url` are why this is worth a type: an error that only says
 * "insufficient credits" leaves the musician with nowhere to go.
 */
export type InsufficientCredits = {
  error: "insufficient_credits"
  balance: number
  required: number
  message: string
  upgrade_url: string
}

export class CreditsError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
    this.name = "CreditsError"
  }
}

/** The caller's current balance. Throws CreditsError with the status on failure. */
export async function fetchBalance(token: string): Promise<CreditBalance> {
  const res = await fetch("/api/credits/balance", {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  const body = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new CreditsError(
      typeof body?.detail === "string"
        ? body.detail
        : "Could not load your credit balance.",
      res.status
    )
  }
  return body as CreditBalance
}

/**
 * Read a 402 body as an `InsufficientCredits`, or null if it is not one.
 *
 * The backend nests it under `detail` (FastAPI's convention); older hand-rolled 402s
 * used the same keys, so this accepts both rather than making callers care.
 */
export function parseInsufficientCredits(
  body: unknown
): InsufficientCredits | null {
  const raw =
    body && typeof body === "object" && "detail" in body
      ? (body as { detail: unknown }).detail
      : body

  if (!raw || typeof raw !== "object") return null

  const candidate = raw as Partial<InsufficientCredits>
  if (candidate.error !== "insufficient_credits") return null

  return {
    error: "insufficient_credits",
    balance: typeof candidate.balance === "number" ? candidate.balance : 0,
    required: typeof candidate.required === "number" ? candidate.required : 0,
    message:
      typeof candidate.message === "string"
        ? candidate.message
        : `Not enough credits — ${candidate.required ?? 0} required, ${candidate.balance ?? 0} available.`,
    upgrade_url:
      typeof candidate.upgrade_url === "string"
        ? candidate.upgrade_url
        : "/settings/billing",
  }
}

/** Format a balance for display: whole numbers stay whole, halves keep one decimal. */
export function formatCredits(balance: number): string {
  return Number.isInteger(balance) ? String(balance) : balance.toFixed(1)
}
