import { describe, expect, it } from "vitest"

import {
  parseClipDragData,
  setClipDragData,
  type ClipDragPayload,
} from "./clip-drag"

/** A minimal DataTransfer stand-in — jsdom's real one works too, but a plain
 * object keeps these tests independent of DOM event construction. */
function fakeDataTransfer(): DataTransfer {
  const store = new Map<string, string>()
  return {
    setData: (type: string, value: string) => store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
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
    }
    setClipDragData(dt, payload)
    expect(parseClipDragData(dt)).toEqual(payload)
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
