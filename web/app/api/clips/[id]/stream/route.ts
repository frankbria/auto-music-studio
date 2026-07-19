import { NextResponse, type NextRequest } from "next/server"

import { ACCESS_COOKIE } from "@/lib/auth"
import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/stream (US-20.0), the
// URL an <audio> element points at. Distinct from the sibling /audio route,
// which this deliberately leaves alone: /audio requires a token and buffers a
// whole body for the Download items.
//
// An <audio src> cannot attach an Authorization header, so to play a *private*
// clip it falls back to the httpOnly `ams_access_token` cookie the browser
// sends automatically (issue #282): if no header is present, that cookie is
// forwarded as the Bearer token. Explicit header (fetch callers) wins; with
// neither, the request reaches the backend anonymously and only public clips
// resolve. The backend enforces visibility either way.
//
// Range is forwarded and the range/caching headers are copied back so seeking
// keeps working — a 206 must arrive at the browser as a 206 with its
// Content-Range intact, or the element silently loses the ability to seek.

// Headers that make the response seekable and cacheable. Content-Type is needed
// for playback; the rest carry the range/caching contract from the backend.
const PASSTHROUGH_HEADERS = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "cache-control",
]

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  // Prefer an explicit Bearer header (fetch callers); fall back to the
  // clip-scoped access cookie so an <audio src> can authenticate (issue #282).
  const cookieToken = request.cookies.get(ACCESS_COOKIE)?.value
  const auth =
    request.headers.get("authorization") ??
    (cookieToken ? `Bearer ${cookieToken}` : null)
  const range = request.headers.get("range")
  const { id } = await ctx.params

  const format = new URL(request.url).searchParams.get("format")
  const query = format ? `?format=${encodeURIComponent(format)}` : ""

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/stream${query}`,
      {
        headers: {
          ...clientIpHeaders(request),
          ...(auth ? { authorization: auth } : {}),
          ...(range ? { range } : {}),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }

  const headers = new Headers()
  for (const name of PASSTHROUGH_HEADERS) {
    const value = res.headers.get(name)
    if (value) headers.set(name, value)
  }

  // 206 is a success here, so gate on the error range rather than res.ok. Errors
  // still keep the headers above: a 416 carries `Content-Range: bytes */{length}`,
  // which is how a seeking client learns the real length and retries.
  if (res.status >= 400) {
    const body = await res.json().catch(() => ({}))
    headers.set("content-type", "application/json")
    headers.delete("content-length") // the JSON body's length differs from upstream's
    return NextResponse.json(body, { status: res.status, headers })
  }

  return new NextResponse(res.body, { status: res.status, headers })
}
