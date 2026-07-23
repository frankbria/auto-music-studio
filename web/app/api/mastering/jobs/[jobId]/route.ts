import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/mastering/jobs/{job_id} (US-21.2). The
// mastering tab polls this after a 202 to drive queued → processing →
// completed/failed. Status/body pass through verbatim (200 with the job detail,
// 401, 404 when the job is unknown or not owned).

export async function GET(
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
      `${BACKEND_URL}/api/v1/mastering/jobs/${encodeURIComponent(jobId)}`,
      { headers: { authorization: auth, accept: "application/json" } }
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
