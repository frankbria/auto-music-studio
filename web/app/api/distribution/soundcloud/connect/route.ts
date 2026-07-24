import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { reemitScLinkCookies } from "@/lib/distribution-server"

const TARGET = `${BACKEND_URL}/api/v1/distribution/soundcloud/connect`

// Begin the SoundCloud link: forward the Bearer token, ask the backend for the
// authorize URL, and re-emit its per-flow PKCE cookies under a path the BFF
// callback route can read back. Mirrors app/api/auth/login/[provider].
export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })

  let res: Response
  try {
    res = await fetch(TARGET, { method: "POST", headers: { authorization: auth } })
  } catch {
    return NextResponse.json({ detail: "SoundCloud is unavailable." }, { status: 502 })
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) return NextResponse.json(body, { status: res.status })
  if (!body.authorization_url) {
    return NextResponse.json({ detail: "Malformed SoundCloud response." }, { status: 502 })
  }

  const out = NextResponse.json({ authorization_url: body.authorization_url })
  reemitScLinkCookies(out, res.headers.getSetCookie())
  return out
}

// Unlink the SoundCloud account (idempotent — the backend 204s even if unlinked).
export async function DELETE(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })

  let res: Response
  try {
    res = await fetch(TARGET, { method: "DELETE", headers: { authorization: auth } })
  } catch {
    return NextResponse.json({ detail: "SoundCloud is unavailable." }, { status: 502 })
  }
  if (res.status === 204) return new NextResponse(null, { status: 204 })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
