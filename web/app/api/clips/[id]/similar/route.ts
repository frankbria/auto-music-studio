import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/clips/{clip_id}/similar (US-17.1). Forwards
// the Bearer token so the song-detail "Related songs" panel can fetch
// suggestions without exposing the backend URL. Only the intended query params
// (scope, bounded limit) are relayed — the raw client query string is NOT
// forwarded, so the client can't smuggle undocumented backend params. Status/
// body pass through verbatim.

const MAX_SIMILAR_LIMIT = 20
const ALLOWED_SCOPES = new Set(["mine", "public", "all"])

/** Whitelist + bound the query params we forward to the backend. */
function safeSearch(url: string): string {
  const incoming = new URL(url).searchParams
  const out = new URLSearchParams()
  const scope = incoming.get("scope")
  if (scope && ALLOWED_SCOPES.has(scope)) out.set("scope", scope)
  const limit = Number(incoming.get("limit"))
  if (Number.isFinite(limit) && limit > 0) {
    out.set("limit", String(Math.min(Math.floor(limit), MAX_SIMILAR_LIMIT)))
  }
  const qs = out.toString()
  return qs ? `?${qs}` : ""
}

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { id } = await ctx.params
  const search = safeSearch(request.url)
  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/similar${search}`,
      { headers: { authorization: auth, accept: "application/json" } }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
