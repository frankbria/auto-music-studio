import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for the generation endpoint (US-16.1). The client holds the
// access token in memory and sends it as a Bearer header; this route forwards it
// to the backend so the backend URL stays server-side. Backend status/body are
// passed through verbatim, so 202 (queued), 401, and 422 (validation) surface
// unchanged to the creation form.

const TARGET = `${BACKEND_URL}/api/v1/generate`

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
    // Backend unreachable / network error — return a controlled 502 instead of
    // letting the route throw an opaque 500.
    return NextResponse.json(
      { detail: "Generation service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
