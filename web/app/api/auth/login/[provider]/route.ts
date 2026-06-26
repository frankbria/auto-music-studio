import { NextResponse } from "next/server"

import { isSupportedProvider, parseStateSetCookies } from "@/lib/auth"
import { BACKEND_URL, STATE_MAX_AGE, cookieOptions } from "@/lib/auth-server"

// Start an OAuth flow: ask the backend for the provider authorization URL and
// re-emit its per-flow state cookie under a path the BFF callback can read back.
export async function POST(
  _request: Request,
  ctx: { params: Promise<{ provider: string }> }
) {
  const { provider } = await ctx.params
  if (!isSupportedProvider(provider)) {
    return NextResponse.json({ detail: "Unknown provider." }, { status: 400 })
  }
  const res = await fetch(`${BACKEND_URL}/api/v1/auth/login/${provider}`, {
    method: "POST",
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) return NextResponse.json(body, { status: res.status })

  const out = NextResponse.json({ authorization_url: body.authorization_url })
  for (const { name, value } of parseStateSetCookies(res.headers.getSetCookie())) {
    out.cookies.set(name, value, cookieOptions(STATE_MAX_AGE))
  }
  return out
}
