import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/clips/{clip_id} (US-17.1). The client holds
// the access token in memory and sends it as a Bearer header; this route
// forwards it so the backend URL stays server-side. The song-detail page fetches
// a single clip through here. Status/body pass through verbatim (200 with the
// clip, 401, 404 when the clip is unknown or not owned).

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
    res = await fetch(`${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}`, {
      headers: { authorization: auth, accept: "application/json" },
    })
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
