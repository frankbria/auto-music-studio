import { afterEach, describe, expect, it, vi } from "vitest"

import { GET as docs } from "@/app/docs/route"
import { GET as schema } from "@/app/openapi.json/route"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("/docs and /openapi.json (#342)", () => {
  it("serves the API's Swagger page as HTML", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response("<html>Swagger UI</html>", {
          headers: { "content-type": "text/html; charset=utf-8" },
        })
      )
    vi.stubGlobal("fetch", fetchMock)

    const res = await docs()

    expect(res.status).toBe(200)
    expect(res.headers.get("content-type")).toContain("text/html")
    expect(await res.text()).toBe("<html>Swagger UI</html>")
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/docs$/)
  })

  it("serves the OpenAPI schema it renders", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ openapi: "3.1.0" }), {
            headers: { "content-type": "application/json" },
          })
        )
    )

    expect(await (await schema()).json()).toEqual({ openapi: "3.1.0" })
  })

  it("502s when the API can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")))
    expect((await docs()).status).toBe(502)
  })
})
