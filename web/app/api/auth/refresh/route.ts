import { NextResponse, type NextRequest } from "next/server"

import { REFRESH_COOKIE } from "@/lib/auth"
import {
  BACKEND_URL,
  REFRESH_MAX_AGE,
  cookieOptions,
} from "@/lib/auth-server"

// Rotate tokens using the httpOnly refresh cookie. Used on app mount to restore
// a session and (later) to renew an expired access token.
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value
  if (!refreshToken) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const res = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    // Don't clear the cookie here: single-use rotation means a concurrent
    // refresh (e.g. a second tab) legitimately 401s on the same token while
    // another request already rotated it — clearing would wipe the valid
    // session. The client treats 401 as signed-out; logout clears explicitly.
    return NextResponse.json(body, { status: res.status })
  }
  if (!body.access_token || !body.refresh_token) {
    return NextResponse.json(
      { detail: "Malformed token response from backend." },
      { status: 502 }
    )
  }

  const out = NextResponse.json({
    access_token: body.access_token,
    expires_in: body.expires_in,
  })
  out.cookies.set(REFRESH_COOKIE, body.refresh_token, cookieOptions(REFRESH_MAX_AGE))
  return out
}
