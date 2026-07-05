import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/lineage (US-17.7). Forwards
// the Bearer token so the song-detail "Generation history" panel can fetch a
// clip's ancestry without exposing the backend URL. The backend endpoint takes
// no query params, so none are forwarded. Status/body pass through verbatim — a
// 404 (clip not found or not owned) surfaces to the client unchanged.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { id } = await ctx.params
  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/lineage`,
      { headers: { authorization: auth, accept: "application/json" } }
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
