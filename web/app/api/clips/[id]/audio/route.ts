import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/audio (US-17.2). The full
// action menu's Download items fetch through here with the in-memory Bearer
// token (a plain <a href> can't attach one). The optional `format` query is
// forwarded so the backend converts (mp3/wav/flac); audio bytes and
// content-type pass through, errors pass through as JSON.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { id } = await ctx.params
  const format = new URL(request.url).searchParams.get("format")
  const query = format ? `?format=${encodeURIComponent(format)}` : ""

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/audio${query}`,
      { headers: { authorization: auth } }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    return NextResponse.json(body, { status: res.status })
  }

  const headers = new Headers()
  for (const name of ["content-type", "content-length"]) {
    const value = res.headers.get(name)
    if (value) headers.set(name, value)
  }
  return new NextResponse(res.body, { status: res.status, headers })
}
