import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/users/me/notifications (#537). Forwards the
// Bearer token and the paging query; status/body pass through verbatim.

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const query = new URL(request.url).search
  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/users/me/notifications${query}`,
      {
        headers: { authorization: auth, accept: "application/json" },
        cache: "no-store",
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Notification service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
