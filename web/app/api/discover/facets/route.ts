import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for the anonymous GET /api/v1/discover/facets (#651): the
// distinct keys and models over public clips, for the Search filter options.

export async function GET(request: NextRequest): Promise<NextResponse> {
  let res: Response
  try {
    res = await fetchWithTimeout(`${BACKEND_URL}/api/v1/discover/facets`, {
      headers: { accept: "application/json", ...clientIpHeaders(request) },
    })
  } catch {
    return NextResponse.json(
      { detail: "Discovery service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
