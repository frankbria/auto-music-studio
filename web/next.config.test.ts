import { describe, expect, it } from "vitest"

import nextConfig, { PAGE_ROUTES } from "./next.config"

describe("page Cache-Control (#338)", () => {
  it("tells every cache to revalidate pages", async () => {
    const rules = (await nextConfig.headers?.()) ?? []
    expect(rules).toEqual([
      {
        source: PAGE_ROUTES,
        headers: [{ key: "Cache-Control", value: "private, no-cache" }],
      },
    ])
  })

  it("covers pages but not hashed assets or the API", () => {
    // The source is one custom regex group, which Next's path-to-regexp anchors and uses as written.
    const pages = new RegExp(`^${PAGE_ROUTES}$`)
    // Files in public/ are covered too: Next serves them with max-age=0 already.
    for (const path of [
      "/",
      "/explore",
      "/song/abc",
      "/studio",
      "/@handle",
      "/favicon.ico",
    ]) {
      expect(pages.test(path), path).toBe(true)
    }
    for (const path of [
      "/_next/static/chunks/a1.js",
      "/_next/image",
      "/api/discover/clips",
      "/api/clips/c1/stream",
    ]) {
      expect(pages.test(path), path).toBe(false)
    }
  })
})
