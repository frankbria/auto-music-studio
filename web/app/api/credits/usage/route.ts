import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/credits/usage (US-26.5), matching the balance proxy
// next door. `days` is the only parameter and is forwarded as-is — the backend bounds it
// (1..365) and rejects anything else with a 422, so there is nothing to validate twice.

const TARGET = `${BACKEND_URL}/api/v1/credits/usage`

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const days = new URL(request.url).searchParams.get("days")
  const url = days ? `${TARGET}?days=${encodeURIComponent(days)}` : TARGET

  let res: Response
  try {
    res = await fetch(url, {
      headers: { authorization: auth, accept: "application/json" },
      cache: "no-store",
    })
  } catch {
    return NextResponse.json(
      { detail: "Credit service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
