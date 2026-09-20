import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/auth/plugin-tokens (issue #515). Minting a
// plugin token was write-only: there was no way to see which ones exist, so a
// leaked token could not be found, let alone revoked. The backend returns only
// live plugin tokens (never the web session's own refresh token) and never the
// token value itself — just the id the revoke route takes.

const TARGET = `${BACKEND_URL}/api/v1/auth/plugin-tokens`

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(TARGET, {
      headers: { authorization: auth, accept: "application/json" },
    })
  } catch {
    return NextResponse.json(
      { detail: "Plugin token service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
