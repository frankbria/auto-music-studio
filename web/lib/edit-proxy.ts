import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Shared same-origin proxy for the editing/iterative endpoints (US-17.3). Every
// modal submits to an `app/api/...` route that delegates here; the client holds
// the access token in memory and sends it as a Bearer header, and this forwards
// it to the backend so the backend URL stays server-side. Backend status/body
// pass through verbatim, so 202 (queued), 401, 402 (insufficient credits), 404,
// and 422 (validation) all surface unchanged to the modal's state machine.

/**
 * Forward a POST to `${BACKEND_URL}${backendPath}` with the caller's bearer
 * token and JSON body. `backendPath` is the absolute backend path, e.g.
 * `/api/v1/clips/abc/crop` or `/api/v1/mashup`.
 */
export async function forwardEdit(
  request: NextRequest,
  backendPath: string
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(`${BACKEND_URL}${backendPath}`, {
      method: "POST",
      headers: {
        authorization: auth,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: await request.text(),
    })
  } catch {
    // Backend unreachable — a controlled 502 the modal can surface as a generic
    // error instead of an opaque 500.
    return NextResponse.json(
      { detail: "Editing service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

/** Build a clip-scoped route handler for `${op}` (crop/speed/extend/…). */
export function clipEditRoute(op: string) {
  return async function POST(
    request: NextRequest,
    ctx: { params: Promise<{ id: string }> }
  ): Promise<NextResponse> {
    const { id } = await ctx.params
    return forwardEdit(request, `/api/v1/clips/${encodeURIComponent(id)}/${op}`)
  }
}
