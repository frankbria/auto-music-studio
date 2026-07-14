import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/studio/export/daw/{job_id} (US-19.6). Once a
// DAW-export job completes, the export hook fetches the ZIP through here with the
// in-memory Bearer token (a plain <a href> can't attach one). The ZIP bytes and
// the content-type/content-disposition headers pass through so the browser
// downloads the bundle with the backend's filename; errors pass through as JSON.

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
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/studio/export/daw/${encodeURIComponent(jobId)}`,
      { headers: { authorization: auth } }
    )
  } catch {
    return NextResponse.json(
      { detail: "Export service is unavailable." },
      { status: 502 }
    )
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    return NextResponse.json(body, { status: res.status })
  }

  const headers = new Headers()
  for (const name of ["content-type", "content-length", "content-disposition"]) {
    const value = res.headers.get(name)
    if (value) headers.set(name, value)
  }
  return new NextResponse(res.body, { status: res.status, headers })
}
