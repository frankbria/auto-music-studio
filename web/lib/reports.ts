// Clip reporting (US-27.2): the categories a listener picks from and the BFF call.

export type ReportCategory = "inappropriate" | "copyright" | "spam" | "other"

export const REPORT_CATEGORIES: { value: ReportCategory; label: string }[] = [
  { value: "inappropriate", label: "Inappropriate content" },
  { value: "copyright", label: "Copyright concern" },
  { value: "spam", label: "Spam" },
  { value: "other", label: "Other" },
]

export type ReportResult =
  { status: "received"; message: string } | { status: "error"; detail: string }

const FALLBACK = "Could not send the report. Please try again."

function detailOf(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === "string" ? detail : null
}

export async function submitClipReport(
  clipId: string,
  category: ReportCategory,
  details: string,
  accessToken: string
): Promise<ReportResult> {
  let res: Response
  try {
    res = await fetch(`/api/clips/${encodeURIComponent(clipId)}/report`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ category, details: details.trim() || null }),
    })
  } catch {
    return { status: "error", detail: FALLBACK }
  }
  const body = await res.json().catch(() => null)
  if (res.status === 401)
    return { status: "error", detail: "Sign in to report clips." }
  if (!res.ok) return { status: "error", detail: detailOf(body) ?? FALLBACK }
  return {
    status: "received",
    message: detailOf(body) ?? "Report received. Our team will review it.",
  }
}
