import type { NextRequest } from "next/server"

import { forwardLabs } from "@/lib/labs-proxy"

// Same-origin proxy for GET /api/v1/labs (#342).
export async function GET(request: NextRequest) {
  return forwardLabs(request, "", "GET")
}
