import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/public (US-20.0) — the
// redacted, is_public-scoped metadata read behind a shared /song/{id} link.
// Unlike the sibling /api/clips/[id] route, a missing Authorization header is
// NOT an error: that's an anonymous visitor, which this endpoint exists to
// serve. The token is forwarded only when present so the backend can recognize
// an owner (and set is_owner). Status/body pass through verbatim: 200, 403 for
// another user's private clip, 404 when unknown/private-to-a-stranger.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  const { id } = await ctx.params

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/public`,
      {
        headers: {
          accept: "application/json",
          ...clientIpHeaders(request),
          ...(auth ? { authorization: auth } : {}),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
