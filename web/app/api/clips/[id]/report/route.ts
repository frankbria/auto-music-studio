import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for POST /api/v1/clips/{id}/report (US-27.2). Auth required;
// status/body pass through verbatim (201, 400 own clip, 403 private, 404, 409 duplicate).

export async function POST(
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
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/report`,
      {
        method: "POST",
        headers: {
          authorization: auth,
          accept: "application/json",
          "content-type": "application/json",
          ...clientIpHeaders(request),
        },
        body: await request.text(),
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
