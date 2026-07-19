import { NextResponse, type NextRequest } from "next/server"

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth"
import { BACKEND_URL, accessCookieOptions, cookieOptions } from "@/lib/auth-server"

// Revoke the refresh token on the backend (best-effort) and clear the cookie.
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value
  if (refreshToken) {
    await fetch(`${BACKEND_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    }).catch(() => {})
  }
  const out = new NextResponse(null, { status: 204 })
  out.cookies.set(REFRESH_COOKIE, "", cookieOptions(0))
  out.cookies.set(ACCESS_COOKIE, "", accessCookieOptions(0))
  return out
}
