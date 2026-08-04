import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/voice-models/{id}/preview (US-25.4). Audio bytes
// and content-type pass through; errors pass through as JSON, with 404 covering
// "not yours" as well as "missing" exactly as the backend intends.

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ modelId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { modelId } = await ctx.params

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/voice-models/${encodeURIComponent(modelId)}/preview`,
      { headers: { authorization: auth } }
    )
  } catch {
    return NextResponse.json(
      { detail: "Voice model service is unavailable." },
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
