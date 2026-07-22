"use client"

import { useState } from "react"
import Link from "next/link"
import { notFound } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  MusicNote01Icon,
  PlayListIcon,
  UserIcon,
} from "@hugeicons/core-free-icons"

import { ExploreClipCard } from "@/components/explore/ExploreClipCard"
import { FollowButton } from "@/components/profile/FollowButton"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAuth } from "@/hooks/use-auth"
import {
  getProfileByHandle,
  profileClips,
  publicPlaylists,
} from "@/lib/profiles"

// Public creator profile (US-20.5) at /@handle. Header (avatar, name, bio, style
// pills, follower/following) + Follow button + Songs / Playlists / About tabs.
// Data comes from the lib/profiles mock seam; the route shim passes the handle.

const compact = new Intl.NumberFormat("en", { notation: "compact" })

/** First-letter initials for the glyph avatar (no authed artwork proxy). */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("")
}

function Stat({
  label,
  value,
  testid,
}: {
  label: string
  value: number
  testid?: string
}) {
  return (
    <span className="flex items-baseline gap-1">
      {/* Compact display, exact count on hover (and for assertions) — a single */}
      {/* follow won't move "12.8K", so the title carries the real number. */}
      <span
        data-testid={testid}
        title={value.toLocaleString("en")}
        className="font-semibold tabular-nums text-foreground"
      >
        {compact.format(value)}
      </span>
      <span className="text-sm text-muted-foreground">{label}</span>
    </span>
  )
}

export function ProfileView({ handle }: { handle: string }) {
  const profile = getProfileByHandle(handle)
  if (!profile) notFound()

  const { isAuthenticated } = useAuth()
  // Optimistic, session-only follow state — there's no Follow backend yet, so the
  // follower count moves locally by ±1 (AC3). The base count is the seam's value.
  // ponytail: no persistence and no self-view guard — the session user carries no
  // handle (AuthUser is {id, email}), so "don't show Follow on my own profile"
  // needs a handle on the token first. Gate on auth alone until then.
  const [following, setFollowing] = useState(false)
  const followerCount = profile.follower_count + (following ? 1 : 0)

  const clips = profileClips(profile)
  const playlists = publicPlaylists()

  return (
    <div className="flex flex-col gap-8 p-8">
      {/* Header */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div
          aria-hidden
          className="flex size-24 shrink-0 items-center justify-center rounded-full bg-muted text-2xl font-semibold text-muted-foreground"
        >
          {initials(profile.display_name) || (
            <HugeiconsIcon icon={UserIcon} size={32} />
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold">{profile.display_name}</h1>
              <p className="text-sm text-muted-foreground">@{profile.handle}</p>
            </div>
            {isAuthenticated && (
              <FollowButton
                following={following}
                onToggle={() => setFollowing((f) => !f)}
              />
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

          <div className="flex flex-wrap gap-4">
            <Stat label="followers" value={followerCount} testid="follower-count" />
            <Stat label="following" value={profile.following_count} />
          </div>
        </div>
      </header>

      {/* Tabs */}
      <Tabs defaultValue="songs">
        <TabsList>
          <TabsTrigger value="songs">Songs</TabsTrigger>
          <TabsTrigger value="playlists">Playlists</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>

        <TabsContent value="songs">
          {clips.length === 0 ? (
            <EmptyState label="No published songs yet." />
          ) : (
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3">
              {clips.map((clip) => (
                <li key={clip.id} className="flex">
                  <ExploreClipCard clip={clip} />
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="playlists">
          {playlists.length === 0 ? (
            <EmptyState label="No public playlists yet." />
          ) : (
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
              {playlists.map((pl) => (
                <li key={pl.id} className="flex">
                  <Link
                    href={`/playlists/${pl.id}`}
                    className="group flex w-full items-center gap-3 rounded-lg border border-border bg-card p-3 outline-none transition-colors hover:bg-accent/50 focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <span
                      aria-hidden
                      className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"
                    >
                      <HugeiconsIcon icon={PlayListIcon} size={22} />
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-medium">{pl.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {pl.clipIds.length}{" "}
                        {pl.clipIds.length === 1 ? "song" : "songs"}
                      </span>
                    </span>
                  </Link>
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
            <p className="text-muted-foreground">
              Joined{" "}
              {new Date(profile.joined_at).toLocaleDateString("en", {
                month: "long",
                year: "numeric",
              })}
            </p>
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
