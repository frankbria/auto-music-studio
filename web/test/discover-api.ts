import { vi } from "vitest"

import type { Clip } from "@/lib/workspace-clips"

/** A GET /api/discover/clips 200 response body. */
export function discoverPage(
  clips: Clip[],
  nextCursor: string | null = null,
  total = clips.length
): Response {
  return new Response(
    JSON.stringify({ clips, next_cursor: nextCursor, total }),
    { status: 200 }
  )
}

/** Query params of every /api/discover/clips request `fetchMock` received, in order. */
export function clipRequests(fetchMock: {
  mock: { calls: unknown[][] }
}): Record<string, string>[] {
  return fetchMock.mock.calls
    .map((call) => new URL(String(call[0]), "http://localhost"))
    .filter((url) => url.pathname === "/api/discover/clips")
    .map((url) => Object.fromEntries(url.searchParams))
}

/** Stub fetch: /api/discover/facets answers `facets`, everything else goes to `clips`. */
export function stubDiscoverFetch(
  clips: (url: string) => Promise<Response> | Response,
  facets = { keys: [] as string[], models: [] as string[] }
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith("/api/discover/facets")) {
      return new Response(JSON.stringify(facets), { status: 200 })
    }
    return clips(url)
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

/**
 * Stub fetch for #653: `/api/discover/clips` marks `ownedId` as the viewer's (`is_owner`) only when the
 * request carries the signed-in test token, the way the API decides it.
 */
export function stubViewerAwareDiscover(clips: Clip[], ownedId: string) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).startsWith("/api/discover/facets")) {
        return new Response(JSON.stringify({ keys: [], models: [] }), {
          status: 200,
        })
      }
      const signedIn =
        new Headers(init?.headers).get("authorization") === "Bearer tok"
      return discoverPage(
        clips.map((clip) => ({
          ...clip,
          is_owner: signedIn && clip.id === ownedId,
        }))
      )
    }
  )
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}
