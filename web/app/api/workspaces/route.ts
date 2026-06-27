import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/workspaces (US-16.5). Forwards the Bearer
// token to the backend so its URL stays server-side; status/body pass through.

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const res = await fetch(`${BACKEND_URL}/api/v1/workspaces`, {
    headers: { authorization: auth, accept: "application/json" },
  })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
