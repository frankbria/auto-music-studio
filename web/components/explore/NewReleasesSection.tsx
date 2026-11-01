"use client"

import { useCallback, useEffect, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { useDiscoveryAuth } from "@/hooks/use-discovery-auth"
import { getNewReleases } from "@/lib/explore"
import type { Clip } from "@/lib/workspace-clips"
import { ExploreClipCard } from "./ExploreClipCard"
import { SectionRow } from "./SectionRow"

// Explore's New Releases row (US-20.1, #651). A client component because it
// reads the same-origin discovery BFF, which a server component can't reach by
// relative URL.

type ReleasesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; clips: Clip[] }

export function NewReleasesSection() {
  const [state, setState] = useState<ReleasesState>({ status: "loading" })

  const { ready, token } = useDiscoveryAuth()

  const load = useCallback(() => {
    getNewReleases(token()).then(
      (clips) => setState({ status: "ready", clips }),
      () => setState({ status: "error" })
    )
  }, [token])

  useEffect(() => {
    if (ready) load()
  }, [load, ready])

  const retry = () => {
    setState({ status: "loading" })
    load()
  }

  return (
    <SectionRow title="New Releases">
      {state.status === "loading" && (
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <HugeiconsIcon
            icon={Loading03Icon}
            size={16}
            className="animate-spin"
          />
          Loading new releases…
        </span>
      )}
      {state.status === "error" && (
        <div role="alert" className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            Couldn&apos;t load new releases.
          </span>
          <Button variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      {state.status === "ready" && state.clips.length === 0 && (
        <p className="text-sm text-muted-foreground">No public songs yet.</p>
      )}
      {state.status === "ready" &&
        state.clips.map((clip) => (
          <ExploreClipCard key={clip.id} clip={clip} />
        ))}
    </SectionRow>
  )
}
