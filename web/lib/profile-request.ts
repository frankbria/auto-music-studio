import type { UserProfile } from "@/lib/profile"

// One GET /api/users/me at a time per access token (#402).
//
// useSubscriptionTier used to issue its own uncached fetch, so every component
// that needed the tier made its own request: song detail mounted two (the menu
// badges plus useSongActions inside), and a workspace of N clip cards mounted
// N + 1. Hooks that mount in the same commit now share the request in flight.
//
// Deliberately NOT a cache of the resolved profile. The entry is dropped the
// moment the request settles, so the next mount fetches again and an upgrade is
// reflected on the next navigation rather than after a full reload — the API
// reads the tier from the database instead of the token claims for the same
// reason. A failed request rejects for every sharer, and each caller keeps its
// own fail-closed default (free).

/** Bound on a single profile request; a hung one must not lock Pro UI forever. */
export const PROFILE_REQUEST_TIMEOUT_MS = 5000

type Inflight = {
  // The fetch implementation the request was made through. Test files swap the
  // global per test; a request made through a different implementation is not
  // the same request, so it is never handed to a later caller.
  via: typeof fetch
  request: Promise<UserProfile>
}

const inflight = new Map<string, Inflight>()

/**
 * Fetch the current user's profile, sharing any request already in flight for
 * the same token. Resolves to the parsed profile; rejects on a non-OK status,
 * a network error, or the timeout.
 */
export function fetchCurrentProfile(accessToken: string): Promise<UserProfile> {
  const via = globalThis.fetch
  const pending = inflight.get(accessToken)
  if (pending && pending.via === via) return pending.request

  const request = via("/api/users/me", {
    headers: { authorization: `Bearer ${accessToken}` },
    signal: AbortSignal.timeout(PROFILE_REQUEST_TIMEOUT_MS),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`profile fetch failed: ${res.status}`)
      return (await res.json()) as UserProfile
    })
    .finally(() => {
      if (inflight.get(accessToken)?.request === request)
        inflight.delete(accessToken)
    })
  inflight.set(accessToken, { via, request })
  return request
}
