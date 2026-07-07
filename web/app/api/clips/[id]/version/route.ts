import { type NextRequest, type NextResponse } from "next/server"

import { forwardEditUpload } from "@/lib/edit-proxy"

// Same-origin proxy for POST /api/v1/clips/{id}/version (US-18.4). Uploads the
// editor's encoded WAV as multipart form data — hence forwardEditUpload rather
// than the JSON clipEditRoute the param-based edits use.
export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await ctx.params
  return forwardEditUpload(request, `/api/v1/clips/${encodeURIComponent(id)}/version`)
}
