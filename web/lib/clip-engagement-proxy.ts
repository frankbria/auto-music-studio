import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Server-side forwarding for the clip engagement routes (#656): play, share and like. Play and share are open to a
// signed-out listener (the token goes along only when present); like needs a token. The client's address is
// forwarded so the backend can count a signed-out listener once per hour.
export async function forwardClipEngagement(
  request: NextRequest,
  id: string,
  action: "play" | "share" | "like",
  method: "POST" | "PUT" | "DELETE",
  { requireAuth }: { requireAuth: boolean }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (requireAuth && !auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/clips/${encodeURIComponent(id)}/${action}`,
      {
        method,
        headers: {
          accept: "application/json",
          ...clientIpHeaders(request),
          ...(auth ? { authorization: auth } : {}),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Clip service is unavailable." },
      { status: 502 }
    )
  }
  if (res.status === 204) return new NextResponse(null, { status: 204 })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
