import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/voice-models (US-25.2/25.3). The client holds
// the access token in memory and sends it as a Bearer header; this route forwards
// it so the backend URL stays server-side. Status and body pass through verbatim.

const TARGET = `${BACKEND_URL}/api/v1/voice-models`

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(TARGET, {
      headers: { authorization: auth, accept: "application/json" },
      cache: "no-store",
    })
  } catch {
    return NextResponse.json(
      { detail: "Voice model service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
