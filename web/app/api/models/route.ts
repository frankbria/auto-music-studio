import { NextResponse } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for the public models list (US-16.4). The backend endpoint
// requires no auth (model metadata is not sensitive), so this route forwards no
// Authorization header — it just keeps the backend URL server-side. Backend
// status/body pass through verbatim.

const TARGET = `${BACKEND_URL}/api/v1/models`

// The list only changes on deploy, so cache the proxied response — every Create
// page visit otherwise incurs a backend round-trip.
export const revalidate = 3600

export async function GET(): Promise<NextResponse> {
  let res: Response
  try {
    // Bound the upstream call so a hung backend can't block this route
    // indefinitely — the catch returns the 502 fallback promptly.
    res = await fetch(TARGET, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    return NextResponse.json(
      { detail: "Model service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
