import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { bodyTooLarge, readTextCapped } from "@/lib/proxy-fetch"

// Same-origin proxy for POST /api/v1/mastering/jobs (US-21.2). The client holds
// the access token in memory and sends it as a Bearer header; this route
// forwards it so the backend URL stays server-side. Status/body pass through
// verbatim: 202 (queued), 401, 402 (insufficient credits), 404, 422.

const TARGET = `${BACKEND_URL}/api/v1/mastering/jobs`

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const payload = await readTextCapped(request)
  if (payload === null) return bodyTooLarge()

  let res: Response
  try {
    res = await fetch(TARGET, {
      method: "POST",
      headers: {
        authorization: auth,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: payload,
    })
  } catch {
    return NextResponse.json(
      { detail: "Mastering service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
