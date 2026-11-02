"use client"

import { useCallback, useEffect, useState, type ReactNode } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { useDiscoveryAuth } from "@/hooks/use-discovery-auth"
import type { DiscoverSort } from "@/lib/discover"
import { getSectionClips } from "@/lib/explore"
import type { Clip } from "@/lib/workspace-clips"
import { ExploreClipCard } from "./ExploreClipCard"
import { SectionRow } from "./SectionRow"

// One Explore row read from the public discovery API (#651, #656). A client component because it reads the
// same-origin discovery BFF, which a server component can't reach by relative URL.

type SectionState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; clips: Clip[] }

export function DiscoverSection({
  title,
  sort,
  ranked = false,
  action,
  emptyText = "No public songs yet.",
}: {
  title: string
  sort: DiscoverSort
  /** Number the cards 1, 2, 3… (Charts). */
  ranked?: boolean
  action?: ReactNode
  emptyText?: string
}) {
  const [state, setState] = useState<SectionState>({ status: "loading" })
  const { ready, token } = useDiscoveryAuth()
  const name = title.toLowerCase()

  const load = useCallback(() => {
    getSectionClips(sort, token()).then(
      (clips) => setState({ status: "ready", clips }),
      () => setState({ status: "error" })
    )
  }, [sort, token])

  useEffect(() => {
    if (ready) load()
  }, [load, ready])

  const retry = () => {
    setState({ status: "loading" })
    load()
  }

  return (
    <SectionRow title={title} action={action}>
      {state.status === "loading" && (
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <HugeiconsIcon
            icon={Loading03Icon}
            size={16}
            className="animate-spin"
          />
          Loading {name}…
        </span>
      )}
      {state.status === "error" && (
        <div role="alert" className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            Couldn&apos;t load {name}.
          </span>
          <Button variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      {state.status === "ready" && state.clips.length === 0 && (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      )}
      {state.status === "ready" &&
        state.clips.map((clip, index) => (
          <ExploreClipCard
            key={clip.id}
            clip={clip}
            rank={ranked ? index + 1 : undefined}
          />
        ))}
    </SectionRow>
  )
}
