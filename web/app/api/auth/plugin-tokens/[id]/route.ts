import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for DELETE /api/v1/auth/plugin-tokens/{id} (issue #515).
// Status passes through verbatim: the backend answers 404 for an unknown id, for
// another user's token and for a web-session token alike, and flattening that
// here would leak which is which.

export async function DELETE(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { id } = await ctx.params
  let res: Response
  try {
    res = await fetch(
      `${BACKEND_URL}/api/v1/auth/plugin-tokens/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        headers: { authorization: auth, accept: "application/json" },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Plugin token service is unavailable." },
      { status: 502 }
    )
  }
  // Success is a bodyless 204; error statuses carry a JSON detail.
  if (res.status === 204) return new NextResponse(null, { status: 204 })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
