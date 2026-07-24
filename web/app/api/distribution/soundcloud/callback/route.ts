import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clearScLinkCookies, collectScLinkCookies } from "@/lib/distribution-server"

const TARGET = `${BACKEND_URL}/api/v1/distribution/soundcloud/callback`

// Finish the SoundCloud link: forward the Bearer token plus the per-flow PKCE
// cookies + code/state to the backend, then clear the single-use cookies.
// Mirrors app/api/auth/callback/[provider].
export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })

  const { code, state } = (await request.json().catch(() => ({}))) as {
    code?: string
    state?: string
  }
  if (!code || !state) {
    return NextResponse.json({ detail: "Missing code or state." }, { status: 400 })
  }

  const cookieHeader = collectScLinkCookies(request)
  let res: Response
  try {
    res = await fetch(TARGET, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: auth,
        ...(cookieHeader ? { cookie: cookieHeader } : {}),
      },
      body: JSON.stringify({ code, state }),
    })
  } catch {
    return NextResponse.json({ detail: "SoundCloud is unavailable." }, { status: 502 })
  }

  const body = await res.json().catch(() => ({}))
  const out = NextResponse.json(body, { status: res.status })
  clearScLinkCookies(request, out)
  return out
}
