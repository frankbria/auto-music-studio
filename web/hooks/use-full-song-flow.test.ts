import { describe, expect, it } from "vitest"

import {
  fullSongReducer,
  type FullSongState,
} from "@/hooks/use-full-song-flow"
import { planSections } from "@/lib/song-structure"

// The wizard's progression logic is a pure reducer, so it's exercised directly
// (the hook wrapper is just useReducer + memoized callbacks).

const SECTIONS = planSections(30, 210)

function seed(overrides: Partial<FullSongState> = {}): FullSongState {
  return {
    status: "planning",
    seedClipId: "seed",
    targetDuration: 210,
    plannedSections: [],
    currentSectionIndex: 0,
    cumulativeClipId: "seed",
    generatedClips: {},
    sectionStatuses: {},
    regenerationInstructions: "",
    regenAttempts: {},
    creditsUsed: 0,
    finalClipId: null,
    ...overrides,
  }
}

/** Drive the whole flow, accepting every section, to a `complete` state. */
function runToCompletion() {
  let state = fullSongReducer(seed(), {
    type: "BEGIN_GENERATION",
    plannedSections: SECTIONS,
    targetDuration: 210,
  })
  for (let i = 0; i < SECTIONS.length; i++) {
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: `clip-${i}` })
    state = fullSongReducer(state, { type: "ACCEPT" })
  }
  return state
}

describe("fullSongReducer", () => {
  it("BEGIN_GENERATION starts generating the first section from the seed", () => {
    const state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    expect(state.status).toBe("generating")
    expect(state.currentSectionIndex).toBe(0)
    expect(state.cumulativeClipId).toBe("seed")
    expect(state.plannedSections).toHaveLength(SECTIONS.length)
  })

  it("SECTION_COMPLETE moves to review, records the clip, and bills a credit", () => {
    let state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0" })
    expect(state.status).toBe("reviewing")
    expect(state.generatedClips[0]).toBe("gen-0")
    expect(state.creditsUsed).toBe(1)
  })

  it("ACCEPT advances to the next section and extends from the accepted clip", () => {
    let state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0" })
    state = fullSongReducer(state, { type: "ACCEPT" })
    expect(state.status).toBe("generating")
    expect(state.currentSectionIndex).toBe(1)
    expect(state.cumulativeClipId).toBe("gen-0")
    expect(state.sectionStatuses[0]).toBe("accepted")
    expect(state.regenerationInstructions).toBe("")
  })

  it("accepting the last section completes the flow with the final clip", () => {
    const state = runToCompletion()
    expect(state.status).toBe("complete")
    expect(state.finalClipId).toBe(`clip-${SECTIONS.length - 1}`)
    expect(state.cumulativeClipId).toBe(`clip-${SECTIONS.length - 1}`)
    expect(state.creditsUsed).toBe(SECTIONS.length)
    expect(
      Object.values(state.sectionStatuses).every((s) => s === "accepted")
    ).toBe(true)
  })

  it("REJECT marks the section rejected but stays in review", () => {
    let state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0" })
    state = fullSongReducer(state, { type: "REJECT" })
    expect(state.status).toBe("reviewing")
    expect(state.sectionStatuses[0]).toBe("rejected")
  })

  it("REGENERATE re-extends from the unchanged cumulative clip with new instructions", () => {
    let state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0" })
    state = fullSongReducer(state, { type: "REJECT" })
    state = fullSongReducer(state, {
      type: "REGENERATE",
      instructions: "more energy",
    })
    expect(state.status).toBe("generating")
    expect(state.currentSectionIndex).toBe(0)
    // Not accepted, so we still extend from the seed, not the rejected clip.
    expect(state.cumulativeClipId).toBe("seed")
    expect(state.regenerationInstructions).toBe("more energy")
    expect(state.regenAttempts[0]).toBe(1)
    expect(state.sectionStatuses[0]).toBe("pending")
  })

  it("a regenerated section that is then accepted bills a second credit", () => {
    let state = fullSongReducer(seed(), {
      type: "BEGIN_GENERATION",
      plannedSections: SECTIONS,
      targetDuration: 210,
    })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0" })
    state = fullSongReducer(state, { type: "REJECT" })
    state = fullSongReducer(state, { type: "REGENERATE", instructions: "x" })
    state = fullSongReducer(state, { type: "SECTION_COMPLETE", clipId: "gen-0b" })
    expect(state.creditsUsed).toBe(2)
    state = fullSongReducer(state, { type: "ACCEPT" })
    expect(state.cumulativeClipId).toBe("gen-0b")
    expect(state.currentSectionIndex).toBe(1)
  })

  it("RESET returns to planning while keeping the seed and target", () => {
    const state = fullSongReducer(runToCompletion(), { type: "RESET" })
    expect(state.status).toBe("planning")
    expect(state.seedClipId).toBe("seed")
    expect(state.finalClipId).toBeNull()
  })

  it("ignores actions that don't match the current phase", () => {
    const planning = seed()
    expect(fullSongReducer(planning, { type: "ACCEPT" })).toBe(planning)
    expect(fullSongReducer(planning, { type: "SECTION_COMPLETE", clipId: "x" })).toBe(
      planning
    )
  })
})
