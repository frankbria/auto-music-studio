"use client"

import { useContext, useEffect, useState } from "react"

import { PlayerContext } from "@/contexts/player-context"
import { useAuth } from "@/hooks/use-auth"
import type { Clip } from "@/lib/workspace-clips"

type Outcome =
  | { id: string; kind: "ok"; clip: Clip }
  | { id: string; kind: "error" }
  | { id: string; kind: "notFound" }

/**
 * Fetch a clip from the public, is_public-scoped BFF read (/api/clips/{id}/public)
 * for the shared song page (US-20.0). The sibling `useClip` requires a token and
 * hits the owner-scoped CRUD read; this one runs for anonymous visitors too and
 * only waits on `authLoading` — long enough to attach a token if the visitor
 * turns out to be signed in, so the response can carry `is_owner`.
 *
 * 403 and 404 both collapse to `notFound`: the backend distinguishes them (403
 * = someone else's private clip) but the page must not, or it would confirm a
 * private clip's existence to whoever holds the link.
 *
 * Outcomes are tagged with their id so a stale result reads as loading rather
 * than showing the previous song under a new URL (same idiom as `useClip`).
 */
export function usePublicClip(id: string | undefined) {
  const { accessToken, isLoading: authLoading } = useAuth()
  // The viewer's server-side like (#656); absent outside a PlayerProvider.
  const syncLikes = useContext(PlayerContext)?.dispatch
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    if (authLoading || !id) return
    let active = true
    const url = `/api/clips/${encodeURIComponent(id)}/public`

    // A token that is present but stale is a 401 (get_current_user_optional
    // rejects an explicitly-supplied bad token rather than treating it as
    // anonymous). The clip may still be public, so retry once without the
    // header: an expired session must not hide a song that a signed-out
    // stranger can see. `is_owner` comes back false, which is the truth for a
    // viewer we can no longer identify.
    // Whether the answer came back for this viewer: only then does `viewer_liked` say anything about them.
    let readAsViewer = false
    async function read(): Promise<Response> {
      if (!accessToken) return fetch(url)
      const res = await fetch(url, {
        headers: { authorization: `Bearer ${accessToken}` },
      })
      if (res.status === 401) return fetch(url)
      readAsViewer = true
      return res
    }

    read()
      .then(async (res) => {
        if (res.status === 404 || res.status === 403) {
          if (active) setOutcome({ id, kind: "notFound" })
          return
        }
        if (!res.ok) throw new Error("fetch failed")
        const clip = (await res.json()) as Clip
        if (!active) return
        if (readAsViewer) {
          syncLikes?.({
            type: "likes/sync",
            liked: clip.viewer_liked ? [clip.id] : [],
            unliked: clip.viewer_liked ? [] : [clip.id],
          })
        }
        setOutcome({ id, kind: "ok", clip })
      })
      .catch(() => {
        if (active) setOutcome({ id, kind: "error" })
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading, syncLikes])

  const current = outcome?.id === id ? outcome : null
  const clip = current?.kind === "ok" ? current.clip : null
  const error = current?.kind === "error"
  const notFound = current?.kind === "notFound"
  // Deliberately not gated on `accessToken` (unlike useClip): an anonymous
  // visitor has none, and treating that as "not loading" would render the
  // error state before the fetch resolves.
  const loading = authLoading || (!!id && current === null)

  return { clip, loading, error, notFound }
}
