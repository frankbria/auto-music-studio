import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for the anonymous GET /api/v1/discover/profiles/{handle}
// (#654), which backs the public profile page. A signed-in viewer's
// Authorization is forwarded so the API can mark their own clips (#653).
// Status/body pass through (404 for an unknown handle or a banned creator).

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ handle: string }> }
): Promise<NextResponse> {
  const { handle } = await ctx.params
  const authorization = request.headers.get("authorization")

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/discover/profiles/${encodeURIComponent(handle)}`,
      {
        headers: {
          accept: "application/json",
          ...clientIpHeaders(request),
          ...(authorization ? { authorization } : {}),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Discovery service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
