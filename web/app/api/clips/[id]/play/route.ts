import type { NextRequest } from "next/server"

import { forwardClipEngagement } from "@/lib/clip-engagement-proxy"

// Same-origin proxy for POST /api/v1/clips/{id}/play (#656). Signed-out callers are counted by address.
export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params
  return forwardClipEngagement(request, id, "play", "POST", {
    requireAuth: false,
  })
}
