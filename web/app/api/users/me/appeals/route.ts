import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/users/me/appeals (US-27.4). Mirrors
// app/api/users/me/route.ts.

const TARGET = `${BACKEND_URL}/api/v1/users/me/appeals`

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }
  const res = await fetch(TARGET, {
    headers: { authorization: auth, accept: "application/json" },
  })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
