import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import {
  bodyTooLarge,
  fetchWithTimeout,
  readTextCapped,
} from "@/lib/proxy-fetch"

// Server-side forwarding for /labs (#342): signed in only, status and body passed through.
export async function forwardLabs(
  request: NextRequest,
  path: string,
  method: "GET" | "PUT"
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }
  const init: RequestInit = {
    method,
    headers: { authorization: auth, accept: "application/json" },
  }
  if (method === "PUT") {
    const payload = await readTextCapped(request)
    if (payload === null) return bodyTooLarge()
    init.headers = { ...init.headers, "content-type": "application/json" }
    init.body = payload
  }
  let res: Response
  try {
    res = await fetchWithTimeout(`${BACKEND_URL}/api/v1/labs${path}`, init)
  } catch {
    return NextResponse.json(
      { detail: "Labs are unavailable right now." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
