import type { IconSvgElement } from "@hugeicons/react"
import {
  ArrowExpand01Icon,
  AudioWave01Icon,
  CropIcon,
  DashboardSpeed02Icon,
  Delete02Icon,
  Exchange01Icon,
  FileExportIcon,
  GitMergeIcon,
  GlobeIcon,
  Idea01Icon,
  Layers01Icon,
  MagicWand01Icon,
  MusicNote01Icon,
  PaintBrush01Icon,
  PencilEdit02Icon,
  RepeatIcon,
  Rocket01Icon,
  SlidersHorizontalIcon,
  Video01Icon,
  VoiceIcon,
} from "@hugeicons/core-free-icons"

// Shared action vocabulary for song/clip operations (US-17.2). The song-detail
// full action menu renders from this registry; ClipCard's menus predate it and
// keep their own item arrays, but their `ClipMenuAction` type now derives from
// the ids here so the two surfaces can't drift apart.

/** Formats offered in a Download submenu (song menu and clip card). */
export type DownloadAction =
  | "download-mp3"
  | "download-wav"
  | "download-flac"
  | "download-stems"

/** Every action reachable from the clip card menus (spec §9.2). */
export type ClipMenuAction =
  | "remix-edit"
  | "open-studio"
  | "open-editor"
  | "cover"
  | "extend"
  | "mashup"
  | "sample"
  | "use-inspiration"
  | "send-mastering"
  | "export-daw"
  | "create-video"
  | DownloadAction
  | "delete"

/** Every action reachable from the song-detail full action menu (US-17.2). */
export type SongActionId =
  | Exclude<ClipMenuAction, "remix-edit">
  | "remix"
  | "repaint"
  | "add-vocal"
  | "remaster"
  | "replace-section"
  | "crop"
  | "adjust-speed"
  | "publish-toggle"

export type SongActionCategory = "edit" | "create" | "audio" | "export" | "manage"

/**
 * How an action is carried out when selected:
 * - `modal`      — opens a workflow modal (content lands in US-17.3+)
 * - `navigation` — routes to another page (editor/studio)
 * - `inline`     — acts in place (remaster one-click, publish toggle, delete confirmation)
 * - `download`   — fetches the clip's audio as a file
 */
export type SongActionWorkflow = "modal" | "navigation" | "inline" | "download"

export type SongActionDefinition = {
  id: SongActionId
  label: string
  icon: IconSvgElement
  workflow: SongActionWorkflow
  /** Gated behind the Pro tier; free-tier users see a locked item. */
  proOnly?: boolean
  destructive?: boolean
}

export type SongActionGroup = {
  category: SongActionCategory
  label: string
  actions: SongActionDefinition[]
}

/** The grouped menu body. Download renders separately as a submenu. */
export const SONG_ACTION_GROUPS: SongActionGroup[] = [
  {
    category: "edit",
    label: "Edit",
    actions: [
      { id: "remix", label: "Remix", icon: RepeatIcon, workflow: "modal" },
      {
        id: "repaint",
        label: "Edit (Repaint)",
        icon: PaintBrush01Icon,
        workflow: "modal",
      },
      {
        // Becomes "navigation" to /editor/{id} when the editor page ships
        // (US-18); until then the placeholder modal keeps users off a 404.
        id: "open-editor",
        label: "Open in Editor",
        icon: PencilEdit02Icon,
        workflow: "modal",
        proOnly: true,
      },
      {
        id: "open-studio",
        label: "Open in Studio",
        icon: SlidersHorizontalIcon,
        workflow: "navigation",
      },
    ],
  },
  {
    category: "create",
    label: "Create",
    actions: [
      { id: "cover", label: "Cover", icon: MusicNote01Icon, workflow: "modal" },
      {
        id: "extend",
        label: "Extend",
        icon: ArrowExpand01Icon,
        workflow: "modal",
      },
      { id: "mashup", label: "Mashup", icon: GitMergeIcon, workflow: "modal" },
      {
        id: "sample",
        label: "Sample from Song",
        icon: AudioWave01Icon,
        workflow: "modal",
      },
      {
        id: "use-inspiration",
        label: "Use as Inspiration",
        icon: Idea01Icon,
        workflow: "modal",
      },
    ],
  },
  {
    category: "audio",
    label: "Audio",
    actions: [
      { id: "add-vocal", label: "Add Vocal", icon: VoiceIcon, workflow: "modal" },
      {
        // One-click, no modal (US-17.3): remaster runs immediately with the
        // default -14 LUFS target and shows inline progress.
        id: "remaster",
        label: "Remaster",
        icon: MagicWand01Icon,
        workflow: "inline",
      },
      {
        id: "replace-section",
        label: "Replace Section",
        icon: Exchange01Icon,
        workflow: "modal",
      },
      { id: "crop", label: "Crop", icon: CropIcon, workflow: "modal" },
      {
        id: "adjust-speed",
        label: "Adjust Speed",
        icon: DashboardSpeed02Icon,
        workflow: "modal",
      },
    ],
  },
  {
    category: "export",
    label: "Export",
    actions: [
      {
        id: "send-mastering",
        label: "Send to Mastering",
        icon: Rocket01Icon,
        workflow: "modal",
        proOnly: true,
      },
      {
        id: "export-daw",
        label: "Export to DAW",
        icon: FileExportIcon,
        workflow: "modal",
        proOnly: true,
      },
      {
        id: "create-video",
        label: "Create Music Video",
        icon: Video01Icon,
        workflow: "modal",
        proOnly: true,
      },
    ],
  },
  {
    category: "manage",
    label: "Manage",
    actions: [
      {
        // Label is static here; the menu shows Publish/Unpublish by state.
        id: "publish-toggle",
        label: "Publish",
        icon: GlobeIcon,
        workflow: "inline",
      },
      {
        id: "delete",
        label: "Delete",
        icon: Delete02Icon,
        workflow: "inline",
        destructive: true,
      },
    ],
  },
]

/**
 * Download submenu items (rendered inside the Export group). MP3/WAV/FLAC hit
 * the audio endpoint directly; stem separation is a backend job, so Stems goes
 * through the modal workflow and is Pro-gated.
 */
export const SONG_DOWNLOAD_ITEMS: SongActionDefinition[] = [
  { id: "download-mp3", label: "MP3", icon: AudioWave01Icon, workflow: "download" },
  { id: "download-wav", label: "WAV", icon: AudioWave01Icon, workflow: "download" },
  {
    id: "download-flac",
    label: "FLAC",
    icon: AudioWave01Icon,
    workflow: "download",
  },
  {
    id: "download-stems",
    label: "Stems",
    icon: Layers01Icon,
    workflow: "modal",
    proOnly: true,
  },
]

const ACTION_INDEX = new Map<SongActionId, SongActionDefinition>(
  [...SONG_ACTION_GROUPS.flatMap((g) => g.actions), ...SONG_DOWNLOAD_ITEMS].map(
    (a) => [a.id, a]
  )
)

/** Look up an action definition by id (download items included). */
export function findSongAction(id: SongActionId): SongActionDefinition | undefined {
  return ACTION_INDEX.get(id)
}
