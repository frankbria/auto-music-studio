import type { NextRequest } from "next/server"

import { forwardClipEngagement } from "@/lib/clip-engagement-proxy"

// Same-origin proxy for PUT/DELETE /api/v1/clips/{id}/like (#656). Signed-in only.
type Context = { params: Promise<{ id: string }> }

export async function PUT(request: NextRequest, ctx: Context) {
  const { id } = await ctx.params
  return forwardClipEngagement(request, id, "like", "PUT", {
    requireAuth: true,
  })
}

export async function DELETE(request: NextRequest, ctx: Context) {
  const { id } = await ctx.params
  return forwardClipEngagement(request, id, "like", "DELETE", {
    requireAuth: true,
  })
}
