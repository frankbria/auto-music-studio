import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

const TARGET = `${BACKEND_URL}/api/v1/distribution/soundcloud/status`

// Report whether the user has a linked SoundCloud account (forwards the Bearer token).
export async function GET(request: NextRequest): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })

  let res: Response
  try {
    res = await fetch(TARGET, { headers: { authorization: auth } })
  } catch {
    return NextResponse.json({ detail: "SoundCloud is unavailable." }, { status: 502 })
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
