"use client"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AddVocalModal } from "@/components/song/modals/AddVocalModal"
import { CoverModal } from "@/components/song/modals/CoverModal"
import { CropModal } from "@/components/song/modals/CropModal"
import { ExtendModal } from "@/components/song/modals/ExtendModal"
import { FullSongWizardModal } from "@/components/song/full-song/FullSongWizardModal"
import { MashupModal } from "@/components/song/modals/MashupModal"
import { RemixModal } from "@/components/song/modals/RemixModal"
import { ReplaceSectionModal } from "@/components/song/modals/ReplaceSectionModal"
import { SampleModal } from "@/components/song/modals/SampleModal"
import { SpeedModal } from "@/components/song/modals/SpeedModal"
import { findSongAction, type SongActionId } from "@/lib/song-actions"
import type { Clip } from "@/lib/workspace-clips"

// US-17.3: dispatch for the modal-workflow actions. useSongActions opens this
// with the selected action id; each editing action routes to its own modal
// (crop/speed/extend/cover/remix/replace-section/sample/add-vocal/mashup).
// `repaint` and `replace-section` are the same regenerate-a-range operation, so
// both open the Replace Section modal. Actions whose modals ship in later
// stories (open-editor, use-inspiration, export/mastering/video, stems) keep the
// "not available yet" placeholder so a menu click never dead-ends.

export type SongActionModalProps = {
  clip: Clip
  /** The modal-workflow action to show, or null when closed. */
  action: SongActionId | null
  onClose: () => void
}

export function SongActionModal({ clip, action, onClose }: SongActionModalProps) {
  switch (action) {
    case "crop":
      return <CropModal clip={clip} open onClose={onClose} />
    case "adjust-speed":
      return <SpeedModal clip={clip} open onClose={onClose} />
    case "extend":
      return <ExtendModal clip={clip} open onClose={onClose} />
    case "get-full-song":
      return <FullSongWizardModal clip={clip} open onClose={onClose} />
    case "cover":
      return <CoverModal clip={clip} open onClose={onClose} />
    case "remix":
      return <RemixModal clip={clip} open onClose={onClose} />
    case "repaint":
    case "replace-section":
      return <ReplaceSectionModal clip={clip} open onClose={onClose} />
    case "sample":
      return <SampleModal clip={clip} open onClose={onClose} />
    case "add-vocal":
      return <AddVocalModal clip={clip} open onClose={onClose} />
    case "mashup":
      return <MashupModal clip={clip} open onClose={onClose} />
    case null:
      return null
    default:
      return <PlaceholderModal action={action} onClose={onClose} />
  }
}

/** Fallback for modal actions whose workflow lands in a later story. */
function PlaceholderModal({
  action,
  onClose,
}: {
  action: SongActionId
  onClose: () => void
}) {
  const definition = findSongAction(action)
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{definition?.label}</DialogTitle>
          <DialogDescription>
            This workflow isn&apos;t available yet — it arrives with an upcoming
            update.
          </DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  )
}
