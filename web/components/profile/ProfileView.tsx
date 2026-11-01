"use client"

import { useCallback, useEffect, useState } from "react"
import { notFound } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Loading03Icon,
  MusicNote01Icon,
  UserIcon,
} from "@hugeicons/core-free-icons"

import { ExploreClipCard } from "@/components/explore/ExploreClipCard"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useDiscoveryAuth } from "@/hooks/use-discovery-auth"
import { fetchPublicProfile, type PublicProfile } from "@/lib/profiles"

// Public creator profile (US-20.5) at /@handle, read from the public profile API
// (#654): avatar, name, bio, style tags, then Songs / About tabs.

type ProfileState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "not-found" }
  | { status: "ready"; profile: PublicProfile }

/** First-letter initials for the glyph avatar (no authed artwork proxy). */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("")
}

export function ProfileView({ handle }: { handle: string }) {
  const [state, setState] = useState<ProfileState>({ status: "loading" })
  const { ready, token } = useDiscoveryAuth()

  const load = useCallback(() => {
    fetchPublicProfile(handle, token()).then(
      (profile) =>
        setState(
          profile ? { status: "ready", profile } : { status: "not-found" }
        ),
      () => setState({ status: "error" })
    )
  }, [handle, token])

  useEffect(() => {
    if (ready) load()
  }, [load, ready])

  const retry = () => {
    setState({ status: "loading" })
    load()
  }

  if (state.status === "not-found") return notFound()

  if (state.status === "loading") {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <HugeiconsIcon
          icon={Loading03Icon}
          size={16}
          className="animate-spin"
        />
        Loading profile…
      </div>
    )
  }

  if (state.status === "error") {
    return (
      <div role="alert" className="flex items-center gap-3 p-8 text-sm">
        <span className="text-muted-foreground">
          Couldn&apos;t load this profile.
        </span>
        <Button variant="outline" size="sm" onClick={retry}>
          Retry
        </Button>
      </div>
    )
  }

  const { profile } = state
  const name = profile.display_name || `@${profile.handle}`
  const joined = `Joined ${new Date(profile.joined_at).toLocaleDateString(
    "en",
    { month: "long", year: "numeric" }
  )}`

  return (
    <div className="flex flex-col gap-8 p-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div
          aria-hidden
          className="flex size-24 shrink-0 items-center justify-center rounded-full bg-muted text-2xl font-semibold text-muted-foreground"
        >
          {initials(profile.display_name ?? "") || (
            <HugeiconsIcon icon={UserIcon} size={32} />
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold">{name}</h1>
            {profile.display_name && (
              <p className="text-sm text-muted-foreground">@{profile.handle}</p>
            )}
          </div>

          {profile.bio && (
            <p className="max-w-prose text-sm text-foreground">{profile.bio}</p>
          )}

          {profile.style_tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {profile.style_tags.map((tag) => (
                <Badge key={tag} variant="secondary">
                  {tag}
                </Badge>
              ))}
            </div>
          )}

          <p className="text-sm text-muted-foreground">{joined}</p>
        </div>
      </header>

      <Tabs defaultValue="songs">
        <TabsList>
          <TabsTrigger value="songs">Songs</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>

        <TabsContent value="songs">
          {profile.clips.length === 0 ? (
            <EmptyState label="No published songs yet." />
          ) : (
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3">
              {profile.clips.map((clip) => (
                <li key={clip.id} className="flex">
                  <ExploreClipCard clip={clip} />
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="about">
          <div className="flex max-w-prose flex-col gap-4 text-sm">
            {profile.bio && <p>{profile.bio}</p>}
            {profile.style_tags.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="font-medium">Styles</span>
                <div className="flex flex-wrap gap-1.5">
                  {profile.style_tags.map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            <p className="text-muted-foreground">{joined}</p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-12 text-muted-foreground">
      <HugeiconsIcon icon={MusicNote01Icon} size={28} aria-hidden />
      <p className="text-sm">{label}</p>
    </div>
  )
}
