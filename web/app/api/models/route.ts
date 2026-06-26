import { NextResponse } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for the public models list (US-16.4). The backend endpoint
// requires no auth (model metadata is not sensitive), so this route forwards no
// Authorization header — it just keeps the backend URL server-side. Backend
// status/body pass through verbatim.

const TARGET = `${BACKEND_URL}/api/v1/models`

export async function GET(): Promise<NextResponse> {
  let res: Response
  try {
    res = await fetch(TARGET, { headers: { accept: "application/json" } })
  } catch {
    return NextResponse.json(
      { detail: "Model service is unavailable." },
      { status: 502 }
    )
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
