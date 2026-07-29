import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/videos/{video_id}/versions (US-22.4).
// Owner-only (edit history), so the Bearer token is required; status/body pass
// through verbatim (200 with the version list, 401/404). The dynamic segment is
// named `jobId` for Next routing but carries a *video* id here.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { jobId: videoId } = await ctx.params
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/videos/${encodeURIComponent(videoId)}/versions`,
      {
        headers: { authorization: auth, accept: "application/json" },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Video service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
