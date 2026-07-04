import { type NextRequest, type NextResponse } from "next/server"

import { forwardEdit } from "@/lib/edit-proxy"

// Same-origin proxy for POST /api/v1/mashup (US-17.3). Not clip-scoped: the
// clip ids travel in the request body, so this forwards straight to the backend.
export function POST(request: NextRequest): Promise<NextResponse> {
  return forwardEdit(request, "/api/v1/mashup")
}
