import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import {
  bodyTooLarge,
  fetchWithTimeout,
  readTextCapped,
} from "@/lib/proxy-fetch"

// Same-origin proxy for POST /api/v1/users/me/notifications/read (#537). Body is
// `{ids?: string[]}` (omitted = all); status/body pass through verbatim.

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const payload = await readTextCapped(request)
  if (payload === null) return bodyTooLarge()

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/users/me/notifications/read`,
      {
        method: "POST",
        headers: {
          authorization: auth,
          accept: "application/json",
          "content-type": "application/json",
        },
        body: payload,
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Notification service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
