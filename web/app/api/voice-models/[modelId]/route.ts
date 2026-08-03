import { NextResponse, type NextRequest } from "next/server"

import { BACKEND_URL } from "@/lib/auth-server"

// Same-origin proxy for PATCH/DELETE /api/v1/voice-models/{id} (US-25.3).
// Status passes through verbatim: 404 covers "not yours" as well as "missing",
// and flattening that here would leak which is which. 409 is "still training".

function target(modelId: string): string {
  return `${BACKEND_URL}/api/v1/voice-models/${encodeURIComponent(modelId)}`
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ modelId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { modelId } = await params

  let res: Response
  try {
    res = await fetch(target(modelId), {
      method: "PATCH",
      headers: { authorization: auth, "content-type": "application/json", accept: "application/json" },
      body: await request.text(),
    })
  } catch {
    return NextResponse.json({ detail: "Voice model service is unavailable." }, { status: 502 })
  }
  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ modelId: string }> }
): Promise<NextResponse> {
  const auth = request.headers.get("authorization")
  if (!auth) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 })
  }

  const { modelId } = await params

  let res: Response
  try {
    res = await fetch(target(modelId), {
      method: "DELETE",
      headers: { authorization: auth, accept: "application/json" },
    })
  } catch {
    return NextResponse.json({ detail: "Voice model service is unavailable." }, { status: 502 })
  }

  // 204 carries no body; forwarding it as JSON would turn a success into a parse error.
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 })
  }

  const body = await res.json().catch(() => ({}))
  return NextResponse.json(body, { status: res.status })
}
