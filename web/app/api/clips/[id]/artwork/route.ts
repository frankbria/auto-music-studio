import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import {
  clientIpHeaders,
  fetchWithTimeout,
  mediaAuthHeaders,
  pickHeaders,
} from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/artwork (#737), the URL an
// <img> points at. Like the /stream proxy: an <img src> can't attach an
// Authorization header, so with no header the httpOnly `ams_access_token` cookie
// is forwarded as the Bearer token, letting an owner see a *private* clip's art.
// With neither, the request is anonymous and only public/unlisted art resolves.
// The backend enforces visibility; a 404 (no art) makes the <img> fall back to
// its placeholder.

const PASSTHROUGH_HEADERS = ["content-type", "content-length", "cache-control"]

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await ctx.params

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/artwork`,
      {
        headers: {
          ...clientIpHeaders(request),
          ...mediaAuthHeaders(request),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    return NextResponse.json(body, { status: res.status })
  }

  return new NextResponse(res.body, {
    status: res.status,
    headers: pickHeaders(res.headers, PASSTHROUGH_HEADERS),
  })
}
