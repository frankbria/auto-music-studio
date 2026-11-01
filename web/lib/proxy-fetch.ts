import { NextResponse } from "next/server"

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

/** The most a JSON-relaying BFF route reads from a request (#567): far above any form, far below a flood. */
export const JSON_BODY_LIMIT = 1024 * 1024

/**
 * A request's body, read up to `limit` bytes (#567). `null` when it is larger, so the route answers
 * `bodyTooLarge()` without buffering the rest or forwarding anything. A declared Content-Length over the
 * limit is refused before reading; the stream is still counted, since that header can be absent or wrong.
 */
export async function readBodyCapped(
  request: Request,
  limit = JSON_BODY_LIMIT
): Promise<Uint8Array<ArrayBuffer> | null> {
  if (Number(request.headers.get("content-length") ?? 0) > limit) return null
  if (!request.body) return new Uint8Array()
  const reader = request.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > limit) {
      await reader.cancel()
      return null
    }
    chunks.push(value)
  }
  const body = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    body.set(chunk, offset)
    offset += chunk.byteLength
  }
  return body
}

/** `readBodyCapped` as text, for the routes that relay a JSON body unchanged. */
export async function readTextCapped(
  request: Request,
  limit = JSON_BODY_LIMIT
): Promise<string | null> {
  const body = await readBodyCapped(request, limit)
  return body === null ? null : new TextDecoder().decode(body)
}

export function bodyTooLarge(): NextResponse {
  return NextResponse.json(
    { detail: "Request body is too large." },
    { status: 413 }
  )
}

/** A capped body as a JSON object, or `{}` when it isn't one, as the callbacks' `.json().catch(() => ({}))` gave. */
export function parseJsonObject(raw: Uint8Array): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(raw))
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : {}
  } catch {
    return {}
  }
}
