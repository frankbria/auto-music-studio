import { NextResponse, type NextRequest } from "next/server"

import { ACCESS_COOKIE } from "@/lib/auth"
import { BACKEND_URL } from "@/lib/auth-server"
import { clientIpHeaders, fetchWithTimeout } from "@/lib/proxy-fetch"

// Same-origin proxy for GET /api/v1/videos/{video_id}/stream (US-22.3), the URL
// a <video> element points at and the Download button links to. The dynamic
// segment is named `jobId` for Next routing (it shares the folder with
// /status), but here it carries a *video* id.
//
// A <video src> / download <a href> can't attach an Authorization header, so to
// play a *private* (owner-only, unpublished) video it falls back to the httpOnly
// access cookie the browser sends automatically (issue #282). Explicit header
// wins; with neither, the request reaches the backend anonymously and only a
// published video on a viewable clip resolves. The backend enforces visibility.
//
// Range and the range/caching/disposition headers pass through so seeking keeps
// working — a 206 must arrive as a 206 with its Content-Range intact.

const PASSTHROUGH_HEADERS = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "cache-control",
  "content-disposition",
]

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ jobId: string }> }
): Promise<NextResponse> {
  const cookieToken = request.cookies.get(ACCESS_COOKIE)?.value
  const auth =
    request.headers.get("authorization") ??
    (cookieToken ? `Bearer ${cookieToken}` : null)
  const range = request.headers.get("range")
  const { jobId: videoId } = await ctx.params

  // Match the value, not mere presence: this is a public proxy, so `?download=0`
  // / `?download=false` must NOT force a download (only the "1" the client sends).
  const download = new URL(request.url).searchParams.get("download") === "1"
  const query = download ? `?download=1` : ""

  let res: Response
  try {
    res = await fetchWithTimeout(
      `${BACKEND_URL}/api/v1/videos/${encodeURIComponent(videoId)}/stream${query}`,
      {
        headers: {
          ...clientIpHeaders(request),
          ...(auth ? { authorization: auth } : {}),
          ...(range ? { range } : {}),
        },
      }
    )
  } catch {
    return NextResponse.json(
      { detail: "Video service is unavailable." },
      { status: 502 }
    )
  }

  const headers = new Headers()
  for (const name of PASSTHROUGH_HEADERS) {
    const value = res.headers.get(name)
    if (value) headers.set(name, value)
  }

  // 206 is a success here, so gate on the error range rather than res.ok; a 416
  // still keeps its Content-Range so a seeking client learns the real length.
  if (res.status >= 400) {
    const body = await res.json().catch(() => ({}))
    headers.set("content-type", "application/json")
    headers.delete("content-length")
    return NextResponse.json(body, { status: res.status, headers })
  }

  return new NextResponse(res.body, { status: res.status, headers })
}
