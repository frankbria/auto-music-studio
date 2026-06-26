import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for the authenticated profile endpoints. The client holds
// the access token in memory and sends it as a Bearer header; this route just
// forwards it to the backend so the backend URL stays server-side and there's
// no cross-origin call. Backend status/body are passed through verbatim, so 409
// (duplicate handle) and 422 (validation) surface unchanged to the form.

const TARGET = `${BACKEND_URL}/api/v1/users/me`

function authHeader(request: NextRequest): string | null {
  return request.headers.get("authorization")
}

async function proxy(
  request: NextRequest,
  method: "GET" | "PATCH"
): Promise<NextResponse> {
  const auth = authHeader(request)
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const init: RequestInit = {
    method,
    headers: { authorization: auth, accept: "application/json" },
  }
  if (method === "PATCH") {
    init.headers = { ...init.headers, "content-type": "application/json" }
    init.body = await request.text()
  }

  const res = await fetch(TARGET, init)
  // Pass an empty (204) response through as-is rather than turning it into a
  // {} JSON body — otherwise the client would treat it as an all-blank profile.
  if (res.status === 204) return new NextResponse(null, { status: 204 })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

export function GET(request: NextRequest) {
  return proxy(request, "GET")
}

export function PATCH(request: NextRequest) {
  return proxy(request, "PATCH")
}
