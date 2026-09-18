import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for POST /api/v1/auth/plugin-token (issue #445). The plugin's
// Platform panel needs a long-lived credential; this mints an independent refresh
// token (the web session's own cookie token is untouched) and hands back only the
// refresh_token — the access_token in the backend response is never needed by the
// browser, so it is stripped rather than passed through.

const TARGET = `${BACKEND_URL}/api/v1/auth/plugin-token`

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(TARGET, {
      method: "POST",
      headers: { authorization: auth, accept: "application/json" },
    })
  } catch {
    return NextResponse.json(
      { detail: "Plugin token service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    return NextResponse.json(body, { status: res.status })
  }
  // Only the refresh_token is the "plugin token" the musician pastes in — never
  // leak the access_token, which the browser has no use for.
  return NextResponse.json({ refresh_token: body.refresh_token })
}
