import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for the billing endpoints (US-26.3), following the pattern in
// app/api/users/me. One catch-all instead of a file per endpoint because these four
// (`subscription`, `history`, `checkout`, `portal`) forward identically — there is no
// per-route behaviour to justify four copies.
//
// The Stripe *webhook* is deliberately NOT proxied here. Stripe calls the backend
// directly, and its signature covers the exact bytes it sent; putting a Next.js hop in
// front risks a re-encoded body that fails verification, and it would expose an
// unauthenticated mutation endpoint on the frontend origin for no benefit.

const ALLOWED = new Set(["subscription", "history", "checkout", "portal"])

async function proxy(
  request: NextRequest,
  method: "GET" | "POST",
  path: string[]
): Promise<NextResponse> {
  const segment = path.join("/")
  if (!ALLOWED.has(segment)) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 })
  }

  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const res = await fetch(`${BACKEND_URL}/api/v1/billing/${segment}`, {
    method,
    headers: { authorization: auth, accept: "application/json" },
  })
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, "GET", (await params).path)
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, "POST", (await params).path)
}
