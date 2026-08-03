import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/voice-models/train/{jobId}/status (US-25.2).
// 404 passes through verbatim: the backend returns it for another user's run as
// well as a missing one, and flattening that here would leak which is which.

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { jobId } = await params

  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/voice-models/train/${encodeURIComponent(jobId)}/status`,
      { headers: { authorization: auth, accept: "application/json" }, cache: "no-store" }
    )
  } catch {
    return NextResponse.json(
      { detail: "Voice model service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
