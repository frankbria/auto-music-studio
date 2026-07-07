import { afterEach, describe, expect, it, vi } from "vitest"
import type { NextRequest } from "next/server"

import { POST as cropPOST } from "@/app/api/clips/[id]/crop/route"
import { POST as mashupPOST } from "@/app/api/mashup/route"
import { clipEditRoute, forwardEdit } from "@/lib/edit-proxy"

afterEach(() => vi.restoreAllMocks())

function req(init: RequestInit = {}): NextRequest {
  return new Request("http://localhost/api/clips/c/crop", {
    method: "POST",
    ...init,
  }) as unknown as NextRequest
}

const params = (id: string) => ({ params: Promise.resolve({ id }) })

describe("forwardEdit", () => {
  it("401s without an Authorization header", async () => {
    const res = await forwardEdit(req(), "/api/v1/clips/c/crop")
    expect(res.status).toBe(401)
  })

  it("forwards token + body to the backend path and passes 202 through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "j1", status: "queued" }), {
        status: 202,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    const res = await forwardEdit(
      req({ headers: { authorization: "Bearer tok" }, body: '{"start":"0s"}' }),
      "/api/v1/clips/c/crop"
    )
    expect(res.status).toBe(202)
    expect(await res.json()).toMatchObject({ job_id: "j1" })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c/crop")
    expect(opts.method).toBe("POST")
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
    expect(opts.body).toBe('{"start":"0s"}')
  })

  it("passes a 402 insufficient-credits body through verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { error: "insufficient_credits", required: 1 } }),
          { status: 402 }
        )
      )
    )
    const res = await forwardEdit(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" }),
      "/api/v1/clips/c/extend"
    )
    expect(res.status).toBe(402)
    expect(await res.json()).toMatchObject({
      detail: { error: "insufficient_credits" },
    })
  })

  it("returns a controlled 502 when the upstream fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await forwardEdit(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" }),
      "/api/v1/clips/c/crop"
    )
    expect(res.status).toBe(502)
  })
})

describe("clipEditRoute", () => {
  it("builds a handler that targets the op path with the url-encoded id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)

    const handler = clipEditRoute("speed")
    await handler(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" }),
      params("id/with slash")
    )
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/api/v1/clips/${encodeURIComponent("id/with slash")}/speed`
    )
  })
})

describe("route handlers", () => {
  it("crop route forwards to the crop op", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ job_id: "j" }), { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)
    const res = await cropPOST(
      req({ headers: { authorization: "Bearer tok" }, body: "{}" }),
      params("abc")
    )
    expect(res.status).toBe(202)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/clips/abc/crop")
  })

  it("mashup route forwards to /api/v1/mashup", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ job_id: "m" }), { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)
    const res = await mashupPOST(
      req({ headers: { authorization: "Bearer tok" }, body: '{"clip_ids":["a","b"]}' })
    )
    expect(res.status).toBe(202)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/mashup")
  })

  it("mashup route 401s without auth", async () => {
    const res = await mashupPOST(req())
    expect(res.status).toBe(401)
  })
})

import { POST as versionPOST } from "@/app/api/clips/[id]/version/route"
import { forwardEditUpload } from "@/lib/edit-proxy"

describe("forwardEditUpload", () => {
  function uploadReq(init: RequestInit = {}): NextRequest {
    return new Request("http://localhost/api/clips/c/version", {
      method: "POST",
      ...init,
    }) as unknown as NextRequest
  }

  it("401s without an Authorization header", async () => {
    const res = await forwardEditUpload(uploadReq(), "/api/v1/clips/c/version")
    expect(res.status).toBe(401)
  })

  it("forwards the raw body and preserves the multipart content-type", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ job_id: "v" }), { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)

    const res = await forwardEditUpload(
      uploadReq({
        headers: {
          authorization: "Bearer tok",
          "content-type": "multipart/form-data; boundary=xyz",
        },
        body: "raw-bytes",
      }),
      "/api/v1/clips/c/version"
    )
    expect(res.status).toBe(202)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/clips/c/version")
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
    expect((opts.headers as Record<string, string>)["content-type"]).toBe(
      "multipart/form-data; boundary=xyz"
    )
  })

  it("returns a controlled 502 when the upstream fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const res = await forwardEditUpload(
      uploadReq({ headers: { authorization: "Bearer tok" }, body: "x" }),
      "/api/v1/clips/c/version"
    )
    expect(res.status).toBe(502)
  })

  it("version route forwards to the version op with the url-encoded id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ job_id: "v" }), { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)
    const res = await versionPOST(
      uploadReq({ headers: { authorization: "Bearer tok" }, body: "x" }),
      params("abc")
    )
    expect(res.status).toBe(202)
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/clips/abc/version")
  })
})
