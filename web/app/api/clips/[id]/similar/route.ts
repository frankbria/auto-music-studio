import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/similar (US-17.1). Forwards
// the Bearer token plus the query string (scope/limit) so the song-detail
// "Related songs" panel can fetch suggestions without exposing the backend URL.
// Status/body pass through verbatim.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { id } = await ctx.params
  const search = new URL(request.url).search
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/similar${search}`,
      {
        headers: { authorization: auth, accept: "application/json" },
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
