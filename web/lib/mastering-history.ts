// Mastering history data seam (US-21.3).
//
// Like the Stage-20 pages (Explore, Notifications, …), mastering history has no
// backend list endpoint yet — the mastering router (US-12.1/12.4) exposes submit,
// detail, previews, and approve, but no `GET /mastering/jobs` listing. This module
// is the local, typed mock layer whose shape mirrors that eventual endpoint. When
// it lands, swap `masteringHistory` for a fetch; the components stay unchanged.
//
// Deferred (not faked) on purpose: the mastering worker doesn't run locally either
// ([[us-21-2-mastering-workflow]]), so real history would be empty here regardless.

import type { MasteringDisplayStatus } from "@/components/mastering/mastering-status"
import type { MasteringProfile, MasteringService, MasteringStatus } from "@/lib/mastering"

/** One past mastering job. `masteredClipId` is set once a master is approved so the
 *  row can link to it (AC4). Mirrors the fields a `GET /mastering/jobs` row would carry. */
export type MasteringHistoryEntry = {
  id: string
  songTitle: string
  profile: MasteringProfile
  service: MasteringService
  status: MasteringStatus
  /** True when a preview from this job has been promoted to the final master. */
  isApproved: boolean
  /** The approved master clip id (present iff isApproved) — links to /song/{id}. */
  masteredClipId?: string
  createdAt: string
}

/** Collapse the backend job status (+ approval) into a display state (AC2). A
 *  COMPLETED job is "approved" once a master was picked, else "preview ready". */
export function masteringDisplayStatus(entry: MasteringHistoryEntry): MasteringDisplayStatus {
  switch (entry.status) {
    case "queued":
      return "queued"
    case "processing":
      return "processing"
    case "failed":
      return "failed"
    case "completed":
      return entry.isApproved ? "approved" : "preview_ready"
  }
}

/** The link a history row navigates to: the approved master's song page, else null. */
export function masteredHref(entry: MasteringHistoryEntry): string | null {
  return entry.isApproved && entry.masteredClipId ? `/song/${entry.masteredClipId}` : null
}

const HOUR = 60 * 60 * 1000

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * HOUR).toISOString()
}

/** Seed history — one row per display state. Approved rows link to real Explore-pool
 *  clip ids (clip-*), the same targets song links use elsewhere, so they resolve. */
export const masteringHistory: MasteringHistoryEntry[] = [
  {
    id: "mj-approved-1",
    songTitle: "Neon Skyline",
    profile: "streaming",
    service: "dolby",
    status: "completed",
    isApproved: true,
    masteredClipId: "clip-neon",
    createdAt: hoursAgo(26),
  },
  {
    id: "mj-preview-1",
    songTitle: "Crownfall",
    profile: "club",
    service: "landr",
    status: "completed",
    isApproved: false,
    createdAt: hoursAgo(3),
  },
  {
    id: "mj-processing-1",
    songTitle: "Gold Rush 88",
    profile: "soundcloud",
    service: "dolby",
    status: "processing",
    isApproved: false,
    createdAt: hoursAgo(0),
  },
  {
    id: "mj-failed-1",
    songTitle: "Paper Lanterns",
    profile: "vinyl",
    service: "bakuage",
    status: "failed",
    isApproved: false,
    createdAt: hoursAgo(48),
  },
]
