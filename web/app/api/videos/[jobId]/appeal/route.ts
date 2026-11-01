import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"
import {
  bodyTooLarge,
  clientIpHeaders,
  fetchWithTimeout,
  readTextCapped,
} from "@/lib/proxy-fetch"

// Same-origin proxy for POST/PATCH /api/v1/videos/{id}/appeal (#623), the video
// counterpart of the clip appeal proxy. Auth required; status/body pass through
// verbatim (201 submitted, 200 info added, 400 no moderation decision, 404 not
// your video, 409 already appealed/no info requested, 422 validation).

async function proxy(
  request: NextRequest,
  method: "POST" | "PATCH",
  id: string
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const payload = await readTextCapped(request)
  if (payload === null) return bodyTooLarge()

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/videos/${encodeURIComponent(id)}/appeal`,
      {
        method,
        headers: {
          authorization: auth,
          accept: "application/json",
          "content-type": "application/json",
          ...clientIpHeaders(request),
        },
        body: payload,
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Video service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  return proxy(request, "POST", (await ctx.params).jobId)
}

export async function PATCH(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  return proxy(request, "PATCH", (await ctx.params).jobId)
}
