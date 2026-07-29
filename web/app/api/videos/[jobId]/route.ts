import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/videos/{video_id} (US-22.3) — a rendered
// video's metadata. Optional auth: the owner (Bearer) sees their unpublished
// video; a published video on a viewable clip resolves anonymously (the song
// page is public). Auth is forwarded only when present. The dynamic segment is
// named `jobId` for Next routing but carries a *video* id here.
//
// Anonymously reachable from the public song page, so it mirrors clips/[id]/public:
// fetchWithTimeout fails closed (502) on a stalled backend, and clientIpHeaders
// preserves the real client IP for backend rate limiting (issue #283).

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  const { jobId: videoId } = await ctx.params
  let res: Response
  try {
    res = await fetchWithTimeout(`${BACKEND_URL}/api/v1/videos/${encodeURIComponent(videoId)}`, {
      headers: {
        accept: "application/json",
        ...clientIpHeaders(request),
        ...(auth ? { authorization: auth } : {}),
      },
    })
  } catch {
    return NextResponse.json(
      { detail: "Video service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
