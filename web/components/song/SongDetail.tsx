"use client"

import { DeleteSongDialog } from "@/components/song/DeleteSongDialog"
import { LineageSection } from "@/components/song/LineageSection"
import { PublishGuardPrompt } from "@/components/song/PublishGuardPrompt"
import { RelatedSongs } from "@/components/song/RelatedSongs"
import { SongActionModal } from "@/components/song/SongActionModal"
import { SongActionsMenu } from "@/components/song/SongActionsMenu"
import { RemasterStatus } from "@/components/song/RemasterStatus"
import { SongHeader } from "@/components/song/SongHeader"
import { SongLyrics } from "@/components/song/SongLyrics"
import { SongMetadata } from "@/components/song/SongMetadata"
import { SongPlayer } from "@/components/song/SongPlayer"
import { usePublicClip } from "@/hooks/use-public-clip"
import { useSongActions } from "@/hooks/use-song-actions"
import { useSubscriptionTier } from "@/hooks/use-subscription-tier"
import { isFullSongEligible } from "@/lib/song-structure"
import type { Clip } from "@/lib/workspace-clips"

// Song-detail view (US-17.1). Holds all the data/auth logic so the App Router
// page (app/song/[id]/page.tsx) stays a thin params→component shim that's hard
// to break and easy to test (this takes a plain clipId). The full action menu
// (US-17.2) dispatches through useSongActions: modal workflows open the
// placeholder container, editor/studio navigate, downloads fetch audio, and
// delete confirms first.
//
// This page is public (US-20.0): a shared /song/{id} link has to open for a
// signed-out visitor, so there is deliberately no auth gate here and the data
// comes from the is_public-scoped public read. Anything that acts on the clip
// is owner-only and hidden accordingly — see SongDetailContent.

export function SongDetail({ clipId }: { clipId: string }) {
  const { clip, loading, error, notFound } = usePublicClip(clipId)

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-8" data-testid="song-loading">
        <div className="h-8 w-64 animate-pulse rounded bg-muted" />
        <div className="h-24 animate-pulse rounded-lg bg-muted" />
        <div className="h-40 animate-pulse rounded-lg bg-muted" />
      </div>
    )
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-5xl p-8" data-testid="song-not-found">
        <h1 className="text-xl font-semibold">Song not found</h1>
        <p className="text-sm text-muted-foreground">
          This song doesn&apos;t exist or you don&apos;t have access to it.
        </p>
      </div>
    )
  }

  if (error || !clip) {
    return (
      <div className="mx-auto max-w-5xl p-8" data-testid="song-error">
        <h1 className="text-xl font-semibold">Couldn&apos;t load this song</h1>
        <p className="text-sm text-muted-foreground">
          Something went wrong. Please try again.
        </p>
      </div>
    )
  }

  // key by clip id so per-song local state (SongHeader's optimistic like,
  // useSongActions' publish/modal state) resets cleanly between songs.
  return <SongDetailContent key={clip.id} clip={clip} />
}

function SongDetailContent({ clip }: { clip: Clip }) {
  const { isFreeTier } = useSubscriptionTier()
  const actions = useSongActions(clip)
  // Server-computed (US-20.0). Absent => not from the public read, so require an
  // explicit true rather than letting undefined read as ownership.
  const isOwner = clip.is_owner === true

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 p-8 lg:flex-row">
      <main className="flex min-w-0 flex-1 flex-col gap-6">
        <SongHeader
          clip={clip}
          isPublic={actions.isPublic}
          isOwner={isOwner}
          onPublishToggle={actions.togglePublish}
          // Every item in the menu acts on the clip (edit, remix, publish,
          // delete), so a visitor gets no menu at all rather than a shell of
          // disabled rows. Like/Dislike/Share stay — anyone can re-share a link.
          actions={
            isOwner ? (
              <SongActionsMenu
                isPublic={actions.isPublic}
                isFreeTier={isFreeTier}
                onAction={actions.handleAction}
                // Full Song only makes sense for a short seed; hide it otherwise.
                hiddenActionIds={
                  isFullSongEligible(clip) ? undefined : ["get-full-song"]
                }
              />
            ) : undefined
          }
        />
        {/* Download errors surface here; delete errors show in their dialog. */}
        {actions.actionError && !actions.confirmingDelete && (
          <p role="alert" className="text-sm text-destructive">
            {actions.actionError}
          </p>
        )}
        <RemasterStatus
          state={actions.remasterState}
          onDismiss={actions.dismissRemaster}
        />
        <SongPlayer clip={clip} />
        <section aria-label="Details" className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Details</h2>
          <SongMetadata clip={clip} />
        </section>
        {/* Provenance chain — renders nothing for an original clip (US-17.7). */}
        <LineageSection clip={clip} />
        <section aria-label="Lyrics" className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Lyrics</h2>
          <SongLyrics lyrics={clip.lyrics} />
        </section>
      </main>
      <aside className="w-full shrink-0 lg:w-80">
        <RelatedSongs clipId={clip.id} isFreeTier={isFreeTier} />
      </aside>
      <SongActionModal
        clip={clip}
        action={actions.activeModal}
        onClose={actions.closeModal}
      />
      <DeleteSongDialog
        open={actions.confirmingDelete}
        title={clip.title}
        deleting={actions.deleting}
        error={actions.actionError}
        onCancel={actions.cancelDelete}
        onConfirm={actions.confirmDelete}
      />
      <PublishGuardPrompt
        guard={actions.publishGuard}
        onClose={actions.dismissPublishGuard}
      />
    </div>
  )
}
