import type { NextRequest } from "next/server"

import { forwardLabs } from "@/lib/labs-proxy"

// Same-origin proxy for PUT /api/v1/labs/{key} (#342): switch an experiment on or off for yourself.
export async function PUT(
  request: NextRequest,
  ctx: { params: Promise<{ key: string }> }
) {
  const { key } = await ctx.params
  return forwardLabs(request, `/${encodeURIComponent(key)}`, "PUT")
}
