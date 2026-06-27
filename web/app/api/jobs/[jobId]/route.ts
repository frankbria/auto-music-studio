import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/jobs/{job_id}/status (US-16.7). The client
// holds the access token in memory and sends it as a Bearer header; this route
// forwards it so the backend URL stays server-side. The creation form polls this
// after a 202 to drive progress → completed/failed. Status/body pass through
// verbatim (200 with the job status, 401, 404 when the job is unknown).

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
      `${BACKEND_URL}/api/v1/jobs/${encodeURIComponent(jobId)}/status`,
      {
        headers: { authorization: auth, accept: "application/json" },
      }
    )
  } catch {
    // Backend unreachable — a controlled 502 the poller can treat as transient
    // instead of an opaque 500 that would read as a failed generation.
    return NextResponse.json(
      { detail: "Job service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
