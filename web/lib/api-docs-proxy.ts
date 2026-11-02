import { NextResponse } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import { fetchWithTimeout } from "@/lib/proxy-fetch"

// The API's own Swagger UI and OpenAPI schema, served from the site's origin at /docs and /openapi.json (#342), so
// every deployment has them without a proxy rule. Swagger's "Try it out" calls /api/v1/... on this origin, which
// reaches the API only where nginx routes /api/v1/ to it; the bare Compose stack serves a working one on the API port.
export async function forwardApiDocs(
  path: "/docs" | "/openapi.json"
): Promise<NextResponse> {
  let res: Response
  try {
    res = await fetchWithTimeout(`${BACKEND_URL}${path}`, {})
  } catch {
    return NextResponse.json(
      { detail: "The API documentation is unavailable right now." },
      { status: 502 }
    )
  }
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "text/plain",
    },
  })
}
