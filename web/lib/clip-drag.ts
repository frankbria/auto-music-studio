// Shared dataTransfer JSON contract for dragging a clip onto the Studio
// timeline (US-19.1): either a fresh clip dragged in from the workspace panel
// ("add", carrying its id/title/duration) or an existing placement being
// repositioned within/between lanes ("move", carrying its own id — the
// destination lane's onDrop already knows the target track, and the reducer
// re-derives the source track by scanning for the placement id, so no
// consumer needs the source track named here). Centralized so the drag
// sources (ClipCard, ClipBlock) and the drop target (TrackLane) can't drift
// on the wire shape.

import {
  TRACK_TYPE_ORDER,
  type TrackType,
} from "@/lib/track-types"

const MIME_TYPE = "application/json"

// The dragged clip's track type, encoded into the dataTransfer *type* string
// (one entry per drag, empty value). Unlike getData() — which browsers only
// expose on drop — dataTransfer.types is readable during dragover, which is
// where TrackLane needs it to show valid/invalid drop feedback (US-19.2).
const TRACK_TYPE_PREFIX = "application/x-ams-track-type-"

export type ClipDragPayload =
  | {
      kind: "add"
      clipId: string
      title: string | null
      duration: number | null
      /** The clip's generation_mode, for track-type matching (US-19.2). */
      generationMode: string | null
      /** The clip's own BPM, for loop-track tempo inheritance (US-19.2). */
      bpm: number | null
    }
  | {
      kind: "move"
      placementId: string
      /** Seconds between the clip's left edge and where the user grabbed it,
       * so a drop places the grab point (not the left edge) at the cursor. */
      grabOffsetSec: number
    }

/** Marks the drag with the clip's track type, readable during dragover. */
export function setDragTrackType(
  dataTransfer: DataTransfer,
  trackType: TrackType
): void {
  dataTransfer.setData(TRACK_TYPE_PREFIX + trackType, "")
}

/** The dragged clip's track type, or null for drags without one (e.g. files). */
export function readDragTrackType(
  dataTransfer: DataTransfer
): TrackType | null {
  for (const entry of dataTransfer.types) {
    if (!entry.startsWith(TRACK_TYPE_PREFIX)) continue
    const type = entry.slice(TRACK_TYPE_PREFIX.length)
    if ((TRACK_TYPE_ORDER as readonly string[]).includes(type)) {
      return type as TrackType
    }
  }
  return null
}

export function setClipDragData(
  dataTransfer: DataTransfer,
  payload: ClipDragPayload
): void {
  dataTransfer.setData(MIME_TYPE, JSON.stringify(payload))
}

/** Parses a drop's dataTransfer back into a ClipDragPayload, or null if absent/invalid. */
export function parseClipDragData(
  dataTransfer: DataTransfer
): ClipDragPayload | null {
  const raw = dataTransfer.getData(MIME_TYPE)
  if (!raw) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof parsed !== "object" || parsed === null) return null
  const p = parsed as Record<string, unknown>
  if (p.kind === "add" && typeof p.clipId === "string") {
    return {
      kind: "add",
      clipId: p.clipId,
      title: typeof p.title === "string" ? p.title : null,
      duration: typeof p.duration === "number" ? p.duration : null,
      generationMode:
        typeof p.generationMode === "string" ? p.generationMode : null,
      bpm: typeof p.bpm === "number" ? p.bpm : null,
    }
  }
  if (p.kind === "move" && typeof p.placementId === "string") {
    return {
      kind: "move",
      placementId: p.placementId,
      grabOffsetSec: typeof p.grabOffsetSec === "number" ? p.grabOffsetSec : 0,
    }
  }
  return null
}
