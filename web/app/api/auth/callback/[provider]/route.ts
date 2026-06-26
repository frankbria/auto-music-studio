import { NextResponse, type NextRequest } from "next/server"

import { REFRESH_COOKIE, isSupportedProvider } from "@/lib/auth"
import {
  BACKEND_URL,
  REFRESH_MAX_AGE,
  clearStateCookies,
  collectStateCookies,
  cookieOptions,
} from "@/lib/auth-server"

// Finish an OAuth flow: forward the state cookie + code to the backend, then
// keep the refresh token in an httpOnly cookie and hand the access token back.
export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ provider: string }> }
) {
  const { provider } = await ctx.params
  if (!isSupportedProvider(provider)) {
    return NextResponse.json({ detail: "Unknown provider." }, { status: 400 })
  }
  const { code, state } = (await request.json().catch(() => ({}))) as {
    code?: string
    state?: string
  }
  if (!code || !state) {
    return NextResponse.json({ detail: "Missing code or state." }, { status: 400 })
  }

  const cookieHeader = collectStateCookies(request)
  const res = await fetch(`${BACKEND_URL}/api/v1/auth/callback/${provider}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
    },
    body: JSON.stringify({ code, state }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) return NextResponse.json(body, { status: res.status })
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
  clearStateCookies(request, out)
  return out
}
