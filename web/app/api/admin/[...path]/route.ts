import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for /api/v1/admin/* (US-27.3). One catch-all because the
// moderation endpoints (queue, log, clip and user actions) forward identically. Only
// GET and POST are exported, which is all the dashboard uses; PUT
// /admin/screening-rules is not proxied and gets Next's 405. The backend's
// require_admin is the gate, so a non-admin's token gets the backend's 403 passed
// straight back. No allowlist: unlike billing, an unknown admin path 404s at the
// backend rather than silently here.

async function proxy(
  request: NextRequest,
  method: "GET" | "POST",
  path: string[]
): Promise<NextResponse> {
  // Dot segments would be normalised out of the URL and reach non-admin routes.
  if (path.some((segment) => segment === "." || segment === "..")) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 })
  }

  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const headers: Record<string, string> = {
    authorization: auth,
    accept: "application/json",
    ...clientIpHeaders(request),
  }
  const init: RequestInit = { method, headers }
  if (method === "POST") {
    headers["content-type"] = "application/json"
    init.body = await request.text()
  }

  const target = `${BACKEND_URL}/api/v1/admin/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`
  let res: Response
  try {
    res = await fetchWithTimeout(target, init)
  } catch {
    return NextResponse.json(
      { detail: "Moderation service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, "GET", (await params).path)
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, "POST", (await params).path)
}
