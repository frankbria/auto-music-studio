import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for POST /api/v1/studio/mixdown (US-19.6). The studio's
// Export Mixdown menu posts the full arrangement here with the in-memory Bearer
// token; this route forwards it so the backend URL stays server-side. Backend
// status/body pass through verbatim, so 202 (queued), 401, and 422 (validation)
// surface unchanged to the export flow.

const TARGET = `${BACKEND_URL}/api/v1/studio/mixdown`

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(TARGET, {
      method: "POST",
      headers: {
        authorization: auth,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: await request.text(),
    })
  } catch {
    return NextResponse.json(
      { detail: "Export service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
