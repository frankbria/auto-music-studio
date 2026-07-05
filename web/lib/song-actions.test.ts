import { describe, expect, it } from "vitest"

import {
  SONG_ACTION_GROUPS,
  SONG_DOWNLOAD_ITEMS,
  findSongAction,
  type SongActionDefinition,
} from "@/lib/song-actions"

const allActions: SongActionDefinition[] = [
  ...SONG_ACTION_GROUPS.flatMap((g) => g.actions),
  ...SONG_DOWNLOAD_ITEMS,
]

describe("SONG_ACTION_GROUPS", () => {
  it("has the five categories in spec order", () => {
    expect(SONG_ACTION_GROUPS.map((g) => g.category)).toEqual([
      "edit",
      "create",
      "audio",
      "export",
      "manage",
    ])
    expect(SONG_ACTION_GROUPS.map((g) => g.label)).toEqual([
      "Edit",
      "Create",
      "Audio",
      "Export",
      "Manage",
    ])
  })

  it("lists every operation from US-17.2 in its category", () => {
    const ids = Object.fromEntries(
      SONG_ACTION_GROUPS.map((g) => [g.category, g.actions.map((a) => a.id)])
    )
    expect(ids.edit).toEqual(["remix", "repaint", "open-editor", "open-studio"])
    expect(ids.create).toEqual([
      "cover",
      "extend",
      "mashup",
      "sample",
      "get-full-song",
      "use-inspiration",
    ])
    expect(ids.audio).toEqual([
      "add-vocal",
      "remaster",
      "replace-section",
      "crop",
      "adjust-speed",
    ])
    // Download is a submenu (SONG_DOWNLOAD_ITEMS), not a flat export action.
    expect(ids.export).toEqual(["send-mastering", "export-daw", "create-video"])
    expect(ids.manage).toEqual(["publish-toggle", "delete"])
  })

  it("gives every action a label and an icon", () => {
    for (const action of allActions) {
      expect(action.label).toBeTruthy()
      expect(action.icon).toBeTruthy()
    }
  })

  it("marks exactly the Pro-gated actions as proOnly", () => {
    const pro = allActions.filter((a) => a.proOnly).map((a) => a.id)
    expect(pro.sort()).toEqual(
      [
        "create-video",
        "download-stems",
        "export-daw",
        "open-editor",
        "send-mastering",
      ].sort()
    )
  })

  it("routes studio to navigation and remaster/publish/delete inline", () => {
    expect(findSongAction("open-studio")?.workflow).toBe("navigation")
    // Remaster is one-click (US-17.3) — inline submit, no modal.
    expect(findSongAction("remaster")?.workflow).toBe("inline")
    expect(findSongAction("publish-toggle")?.workflow).toBe("inline")
    expect(findSongAction("delete")?.workflow).toBe("inline")
  })

  it("routes unbuilt destinations and generation/audio operations to modals", () => {
    for (const id of [
      "remix",
      "repaint",
      // open-editor flips to navigation when the editor page ships (US-18).
      "open-editor",
      "cover",
      "extend",
      "mashup",
      "sample",
      "use-inspiration",
      "add-vocal",
      "replace-section",
      "crop",
      "adjust-speed",
      "send-mastering",
      "export-daw",
      "create-video",
    ] as const) {
      expect(findSongAction(id)?.workflow).toBe("modal")
    }
  })

  it("marks only Delete as destructive", () => {
    const destructive = allActions.filter((a) => a.destructive).map((a) => a.id)
    expect(destructive).toEqual(["delete"])
  })
})

describe("SONG_DOWNLOAD_ITEMS", () => {
  it("offers MP3/WAV/FLAC as direct downloads and Stems as a Pro modal", () => {
    expect(SONG_DOWNLOAD_ITEMS.map((a) => a.id)).toEqual([
      "download-mp3",
      "download-wav",
      "download-flac",
      "download-stems",
    ])
    for (const id of ["download-mp3", "download-wav", "download-flac"] as const) {
      const item = findSongAction(id)
      expect(item?.workflow).toBe("download")
      expect(item?.proOnly).toBeFalsy()
    }
    // Stem separation is a backend job (POST /clips/{id}/stems), not a file
    // fetch — it goes through the modal workflow like other generation actions.
    expect(findSongAction("download-stems")?.workflow).toBe("modal")
  })
})

describe("findSongAction", () => {
  it("resolves any id, including download submenu items", () => {
    expect(findSongAction("remix")?.label).toBe("Remix")
    expect(findSongAction("download-wav")?.label).toBe("WAV")
  })
})
