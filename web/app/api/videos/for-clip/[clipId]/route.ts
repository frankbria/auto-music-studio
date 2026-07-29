import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/videos/for-clip/{clip_id} (US-22.3) — the
// published video for a clip, backing the song page's "Music video" section.
// Optional auth (the song page is public): auth is forwarded only when present.
// Verbatim pass-through — 200 with the video, or 404 when the clip has no
// published video (or isn't viewable), which the page reads as "no video".

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ clipId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  const { clipId } = await ctx.params
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/videos/for-clip/${encodeURIComponent(clipId)}`,
      { headers: { accept: "application/json", ...(auth ? { authorization: auth } : {}) } }
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
