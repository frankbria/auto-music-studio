import { describe, expect, it } from "vitest"

import {
  parseClipDragData,
  readDragTrackType,
  setClipDragData,
  setDragTrackType,
  type ClipDragPayload,
} from "./clip-drag"

/** A minimal DataTransfer stand-in — jsdom's real one works too, but a plain
 * object keeps these tests independent of DOM event construction. */
function fakeDataTransfer(): DataTransfer {
  const store = new Map<string, string>()
  return {
    setData: (type: string, value: string) => store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
    get types() {
      return [...store.keys()]
    },
  } as unknown as DataTransfer
}

describe("setClipDragData / parseClipDragData round-trip", () => {
  it("round-trips an 'add' payload (new clip from the workspace panel)", () => {
    const dt = fakeDataTransfer()
    const payload: ClipDragPayload = {
      kind: "add",
      clipId: "clip-a",
      title: "My Clip",
      duration: 12,
      generationMode: "sound",
      bpm: 90,
    }
    setClipDragData(dt, payload)
    expect(parseClipDragData(dt)).toEqual(payload)
  })

  it("defaults missing generationMode/bpm to null on an 'add' payload", () => {
    const dt = fakeDataTransfer()
    dt.setData(
      "application/json",
      JSON.stringify({ kind: "add", clipId: "clip-a", title: "A", duration: 3 })
    )
    expect(parseClipDragData(dt)).toEqual({
      kind: "add",
      clipId: "clip-a",
      title: "A",
      duration: 3,
      generationMode: null,
      bpm: null,
    })
  })

  it("round-trips a 'move' payload (existing placement being repositioned)", () => {
    const dt = fakeDataTransfer()
    const payload: ClipDragPayload = {
      kind: "move",
      placementId: "p1",
      grabOffsetSec: 1.25,
    }
    setClipDragData(dt, payload)
    expect(parseClipDragData(dt)).toEqual(payload)
  })

  it("defaults a missing grabOffsetSec to 0 on a 'move' payload", () => {
    const dt = fakeDataTransfer()
    dt.setData(
      "application/json",
      JSON.stringify({ kind: "move", placementId: "p1" })
    )
    expect(parseClipDragData(dt)).toEqual({
      kind: "move",
      placementId: "p1",
      grabOffsetSec: 0,
    })
  })
})

describe("parseClipDragData validation", () => {
  it("returns null when no data was set", () => {
    expect(parseClipDragData(fakeDataTransfer())).toBeNull()
  })

  it("returns null for malformed JSON", () => {
    const dt = fakeDataTransfer()
    dt.setData("application/json", "{not json")
    expect(parseClipDragData(dt)).toBeNull()
  })

  it("returns null for an unrecognized shape", () => {
    const dt = fakeDataTransfer()
    dt.setData("application/json", JSON.stringify({ kind: "add" })) // missing clipId
    expect(parseClipDragData(dt)).toBeNull()
  })

  it("returns null for an unknown kind", () => {
    const dt = fakeDataTransfer()
    dt.setData("application/json", JSON.stringify({ kind: "delete" }))
    expect(parseClipDragData(dt)).toBeNull()
  })
})

describe("drag track-type entry (readable during dragover, unlike getData)", () => {
  it("round-trips the dragged clip's track type via the dataTransfer type list", () => {
    const dt = fakeDataTransfer()
    setDragTrackType(dt, "loop")
    expect(readDragTrackType(dt)).toBe("loop")
  })

  it("coexists with the JSON payload entry", () => {
    const dt = fakeDataTransfer()
    setClipDragData(dt, {
      kind: "add",
      clipId: "c1",
      title: null,
      duration: null,
      generationMode: "upload",
      bpm: null,
    })
    setDragTrackType(dt, "audio")
    expect(readDragTrackType(dt)).toBe("audio")
    expect(parseClipDragData(dt)?.kind).toBe("add")
  })

  it("returns null when no track-type entry is present (external drags)", () => {
    const dt = fakeDataTransfer()
    dt.setData("text/plain", "whatever")
    expect(readDragTrackType(dt)).toBeNull()
  })
})
