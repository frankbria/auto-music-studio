import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/releases (#748): the caller's releases for the distribution dashboard.
export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(`${BACKEND_URL}/api/v1/releases`, {
      headers: { authorization: auth, accept: "application/json" },
    })
  } catch {
    return NextResponse.json(
      { detail: "Release service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
