import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for the anonymous GET /api/v1/discover/clips (#651), which
// backs Feed, Explore and Search. Only the documented query params are relayed,
// never the raw query string, so a client can't smuggle undocumented backend
// params; the backend validates their values (422). No Authorization is
// forwarded: discovery is the same for everyone. Status/body pass through.

const FORWARDED_PARAMS = [
  "q",
  "style",
  "bpm_min",
  "bpm_max",
  "key",
  "model",
  "sort",
  "limit",
  "cursor",
]

export async function GET(request: NextRequest): Promise<NextResponse> {
  const incoming = new URL(request.url).searchParams
  const forwarded = new URLSearchParams()
  for (const name of FORWARDED_PARAMS) {
    const value = incoming.get(name)
    if (value) forwarded.set(name, value)
  }
  const query = forwarded.toString()

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/discover/clips${query ? `?${query}` : ""}`,
      { headers: { accept: "application/json", ...clientIpHeaders(request) } }
    )
  } catch {
    return NextResponse.json(
      { detail: "Discovery service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
