import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for POST /api/v1/videos/{video_id}/edit (US-22.4).
// Owner-only, so the Bearer token is required; status/body pass through verbatim
// (202 with the job id, 401/402/404/422/503). The dynamic segment is named
// `jobId` for Next routing but carries a *video* id here.

export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { jobId: videoId } = await ctx.params
  const body = await request.text()
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/videos/${encodeURIComponent(videoId)}/edit`,
      {
        method: "POST",
        headers: {
          authorization: auth,
          "content-type": "application/json",
          accept: "application/json",
        },
        body,
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Video service is unavailable." },
      { status: 502 }
    )
  }
  const payload = await res.json().catch(() => ({}))
  return NextResponse.json(payload, { status: res.status })
}
