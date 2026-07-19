// Shared fetch wrapper for the same-origin BFF proxies. Adds an abort-based
// timeout so a stalled upstream fails closed (the caller's catch returns 502)
// instead of hanging the request indefinitely.

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  ms = 10_000
): Promise<Response> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), ms)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }
}

// Forward the real client IP so the backend's per-IP rate limiter keys per
// visitor, not per BFF egress IP (#283). A same-origin proxy calls the backend
// server-side, so without this every visitor collapses into one shared bucket.
// Reads the client IP the fronting proxy set (leftmost X-Forwarded-For =
// original client; X-Real-IP as fallback) and re-forwards a single value.
//
// Trust note: this value is only as trustworthy as the header on the inbound
// request. A production deployment must sit behind an edge proxy that
// sets/replaces X-Forwarded-For with the true client — a directly-exposed
// Next server would let a client inject its own value here (inherent to any
// X-Forwarded-For scheme). Returns {} when no such header is present (local dev
// with no fronting proxy) so the backend safely falls back to the peer IP.
export function clientIpHeaders(request: {
  headers: Headers
}): Record<string, string> {
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0].trim() ||
    request.headers.get("x-real-ip")?.trim()
  return ip ? { "x-forwarded-for": ip } : {}
}
