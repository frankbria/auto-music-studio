import { describe, expect, it } from "vitest"

import {
  SONG_ACTION_GROUPS,
  SONG_DOWNLOAD_ITEMS,
  isSongActionLocked,
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
    // create-video is deliberately absent (US-26.2): the free tier gets 720p, so the
    // form must stay reachable and the Pro boundary is the resolution inside it.
    expect(pro.sort()).toEqual(
      [
        "download-flac",
        "download-stems",
        "download-wav",
        "export-daw",
        "open-editor",
        "send-mastering",
      ].sort()
    )
  })

  it("gives every Pro-gated action a capability for the upgrade prompt", () => {
    // Without one the modal falls back to generic copy, which defeats leading with
    // the feature the musician actually reached for (US-26.2 AC2).
    for (const action of allActions.filter((a) => a.proOnly)) {
      expect(action.capability, `${action.id} has no capability`).toBeTruthy()
    }
  })

  it("routes studio to navigation and remaster/publish/delete inline", () => {
    expect(findSongAction("open-studio")?.workflow).toBe("navigation")
    // Open in Editor navigates to /editor/{id} (US-18.1).
    expect(findSongAction("open-editor")?.workflow).toBe("navigation")
    // Create Music Video navigates to /video/{id} (US-22.2).
    expect(findSongAction("create-video")?.workflow).toBe("navigation")
    // Remaster is one-click (US-17.3) — inline submit, no modal.
    expect(findSongAction("remaster")?.workflow).toBe("inline")
    expect(findSongAction("publish-toggle")?.workflow).toBe("inline")
    expect(findSongAction("delete")?.workflow).toBe("inline")
  })

  it("routes unbuilt destinations and generation/audio operations to modals", () => {
    for (const id of [
      "remix",
      "repaint",
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
    for (const id of [
      "download-mp3",
      "download-wav",
      "download-flac",
    ] as const) {
      expect(findSongAction(id)?.workflow).toBe("download")
    }
    // US-26.2: "MP3 download only" on the free tier. MP3 stays open; the lossless two
    // are gated, matching what GET /clips/{id}/audio?format= enforces.
    expect(findSongAction("download-mp3")?.proOnly).toBeFalsy()
    expect(findSongAction("download-wav")?.proOnly).toBe(true)
    expect(findSongAction("download-flac")?.proOnly).toBe(true)
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

describe("isSongActionLocked", () => {
  const wav = findSongAction("download-wav")
  const mastering = findSongAction("send-mastering")

  it("does not lock anything for a Pro account", () => {
    expect(isSongActionLocked(wav, { isFreeTier: false, nativeFormat: "mp3" })).toBe(false)
  })

  it("locks a lossless download that is a genuine conversion", () => {
    expect(isSongActionLocked(wav, { isFreeTier: true, nativeFormat: "mp3" })).toBe(true)
  })

  it("does not lock a download of the clip's own stored format", () => {
    // Mirrors the API: the lossless gate fires on `format !== native_format`, so a
    // free musician may download back the wav they uploaded.
    expect(isSongActionLocked(wav, { isFreeTier: true, nativeFormat: "wav" })).toBe(false)
    expect(isSongActionLocked(wav, { isFreeTier: true, nativeFormat: "WAV" })).toBe(false)
  })

  it("leaves non-download Pro actions locked regardless of format", () => {
    // The carve-out is about serving a stored file, not about capabilities at large.
    expect(isSongActionLocked(mastering, { isFreeTier: true, nativeFormat: "wav" })).toBe(true)
  })

  it("locks when the format is unknown", () => {
    expect(isSongActionLocked(wav, { isFreeTier: true, nativeFormat: null })).toBe(true)
  })
})
