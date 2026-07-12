// Shared dataTransfer JSON contract for dragging a clip onto the Studio
// timeline (US-19.1): either a fresh clip dragged in from the workspace panel
// ("add", carrying its id/title/duration) or an existing placement being
// repositioned within/between lanes ("move", carrying its own id + the track
// it started on). Centralized so the drag sources (ClipCard, ClipBlock) and
// the drop target (TrackLane) can't drift on the wire shape.

const MIME_TYPE = "application/json"

export type ClipDragPayload =
  | {
      kind: "add"
      clipId: string
      title: string | null
      duration: number | null
    }
  | { kind: "move"; placementId: string; sourceTrackId: string }

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
    }
  }
  if (
    p.kind === "move" &&
    typeof p.placementId === "string" &&
    typeof p.sourceTrackId === "string"
  ) {
    return {
      kind: "move",
      placementId: p.placementId,
      sourceTrackId: p.sourceTrackId,
    }
  }
  return null
}
