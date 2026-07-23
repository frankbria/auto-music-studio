import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for POST /api/v1/mastering/jobs/{job_id}/approve (US-21.2).
// Promotes a chosen preview to the final master. Status/body pass through
// verbatim (200 with {clip_id, audio_url}, 401, 404, 422).

export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { jobId } = await ctx.params
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/mastering/jobs/${encodeURIComponent(jobId)}/approve`,
      {
        method: "POST",
        headers: {
          authorization: auth,
          "content-type": "application/json",
          accept: "application/json",
        },
        body: await request.text(),
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Mastering service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
