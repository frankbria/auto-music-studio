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

// Must track the billing router. A new endpoint that is not listed here 404s at the
// proxy with no sign of why — which is exactly what happened to `packs`/`topup` when
// US-26.4 added them and this line was not touched.
const ALLOWED = new Set([
  "subscription",
  "history",
  "checkout",
  "portal",
  "packs",
  "topup",
])

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

  // The body has to be forwarded, not just the method and auth header. `topup` posts
  // `{ pack_id }`, and dropping it made the backend reject the request as invalid
  // instead of opening Stripe Checkout — the purchase was broken end-to-end while both
  // the component tests (fetch stubbed in the browser) and the API tests (backend called
  // directly) passed, because neither exercised this hop.
  const init: RequestInit = {
    method,
    headers: { authorization: auth, accept: "application/json" },
  }
  if (method === "POST") {
    const body = await request.text()
    if (body) {
      init.headers = { ...init.headers, "content-type": "application/json" }
      init.body = body
    }
  }

  const res = await fetch(`${BACKEND_URL}/api/v1/billing/${segment}`, init)
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
