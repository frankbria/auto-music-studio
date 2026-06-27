import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for GET /api/v1/clips (US-16.5). The client holds the access
// token in memory and sends it as a Bearer header; this route forwards it plus
// the query string (search/sort/page/per_page/workspace_id) to the backend so
// the backend URL stays server-side. Status/body pass through verbatim.

export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const search = new URL(request.url).search
  const res = await fetch(`${BACKEND_URL}/api/v1/clips${search}`, {
    headers: { authorization: auth, accept: "application/json" },
  })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
