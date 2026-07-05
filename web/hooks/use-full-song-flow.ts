"use client"

import { useMemo, useReducer } from "react"

import type { Section } from "@/lib/song-structure"

// State machine for the Get Full Song wizard (US-17.4). Pure progression logic:
// it tracks which section we're on, each section's accept/reject status, and the
// cumulative clip the next extend builds on — but owns no async. The generation
// step drives one extend via useClipEdit and reports the result back with
// SECTION_COMPLETE, so this reducer stays trivially testable.

export type FullSongStatus = "planning" | "generating" | "reviewing" | "complete"

export type SectionStatus = "pending" | "accepted" | "rejected"

export type FullSongState = {
  status: FullSongStatus
  /** The original short clip; the flow always starts from here. */
  seedClipId: string
  targetDuration: number
  plannedSections: Section[]
  currentSectionIndex: number
  /** Clip the next extend continues from: the seed, then each accepted result. */
  cumulativeClipId: string
  /** Section index → most recently generated clip id (awaiting review). */
  generatedClips: Record<number, string>
  sectionStatuses: Record<number, SectionStatus>
  /** Extra style/instructions for the *current* section's next generation. */
  regenerationInstructions: string
  /** Section index → number of regeneration attempts (for UX feedback). */
  regenAttempts: Record<number, number>
  /** One credit per generated section (incremented on every completion). */
  creditsUsed: number
  /** The finished song — the last accepted extend result. */
  finalClipId: string | null
}

export type FullSongAction =
  | { type: "BEGIN_GENERATION"; plannedSections: Section[]; targetDuration: number }
  | { type: "SECTION_COMPLETE"; clipId: string }
  | { type: "ACCEPT" }
  | { type: "REJECT" }
  | { type: "REGENERATE"; instructions: string }
  | { type: "RESET" }

function initialState(seedClipId: string, targetDuration: number): FullSongState {
  return {
    status: "planning",
    seedClipId,
    targetDuration,
    plannedSections: [],
    currentSectionIndex: 0,
    cumulativeClipId: seedClipId,
    generatedClips: {},
    sectionStatuses: {},
    regenerationInstructions: "",
    regenAttempts: {},
    creditsUsed: 0,
    finalClipId: null,
  }
}

export function fullSongReducer(
  state: FullSongState,
  action: FullSongAction
): FullSongState {
  switch (action.type) {
    case "BEGIN_GENERATION":
      return {
        ...initialState(state.seedClipId, action.targetDuration),
        status: "generating",
        plannedSections: action.plannedSections,
      }

    case "SECTION_COMPLETE": {
      if (state.status !== "generating") return state
      return {
        ...state,
        status: "reviewing",
        generatedClips: {
          ...state.generatedClips,
          [state.currentSectionIndex]: action.clipId,
        },
        creditsUsed: state.creditsUsed + 1,
      }
    }

    case "ACCEPT": {
      if (state.status !== "reviewing") return state
      const index = state.currentSectionIndex
      const acceptedClipId = state.generatedClips[index]
      if (!acceptedClipId) return state
      const sectionStatuses = { ...state.sectionStatuses, [index]: "accepted" as const }
      const isLast = index >= state.plannedSections.length - 1
      if (isLast) {
        return {
          ...state,
          status: "complete",
          sectionStatuses,
          cumulativeClipId: acceptedClipId,
          finalClipId: acceptedClipId,
        }
      }
      return {
        ...state,
        status: "generating",
        sectionStatuses,
        cumulativeClipId: acceptedClipId,
        currentSectionIndex: index + 1,
        regenerationInstructions: "",
      }
    }

    case "REJECT": {
      if (state.status !== "reviewing") return state
      // Stay in review with the regeneration UI enabled; the clip stays visible
      // so the user can keep previewing while deciding what to change.
      return {
        ...state,
        sectionStatuses: {
          ...state.sectionStatuses,
          [state.currentSectionIndex]: "rejected",
        },
      }
    }

    case "REGENERATE": {
      if (state.status !== "reviewing") return state
      const index = state.currentSectionIndex
      // Re-extend from the same cumulative clip (unchanged since the last accept),
      // steered by the new instructions. Reset this section to pending.
      return {
        ...state,
        status: "generating",
        regenerationInstructions: action.instructions,
        regenAttempts: {
          ...state.regenAttempts,
          [index]: (state.regenAttempts[index] ?? 0) + 1,
        },
        sectionStatuses: { ...state.sectionStatuses, [index]: "pending" },
      }
    }

    case "RESET":
      return initialState(state.seedClipId, state.targetDuration)

    default:
      return state
  }
}

export type UseFullSongFlow = {
  state: FullSongState
  /** The section currently generating or under review, if any. */
  currentSection: Section | null
  totalSections: number
  isLastSection: boolean
  beginGeneration: (plannedSections: Section[], targetDuration: number) => void
  sectionComplete: (clipId: string) => void
  accept: () => void
  reject: () => void
  regenerate: (instructions: string) => void
  reset: () => void
}

/** Owns the wizard's progression state for one seed clip. */
export function useFullSongFlow(
  seedClipId: string,
  initialTargetDuration: number
): UseFullSongFlow {
  const [state, dispatch] = useReducer(
    fullSongReducer,
    undefined,
    () => initialState(seedClipId, initialTargetDuration)
  )

  return useMemo(() => {
    const total = state.plannedSections.length
    return {
      state,
      currentSection: state.plannedSections[state.currentSectionIndex] ?? null,
      totalSections: total,
      isLastSection: total > 0 && state.currentSectionIndex >= total - 1,
      beginGeneration: (plannedSections, targetDuration) =>
        dispatch({ type: "BEGIN_GENERATION", plannedSections, targetDuration }),
      sectionComplete: (clipId) => dispatch({ type: "SECTION_COMPLETE", clipId }),
      accept: () => dispatch({ type: "ACCEPT" }),
      reject: () => dispatch({ type: "REJECT" }),
      regenerate: (instructions) => dispatch({ type: "REGENERATE", instructions }),
      reset: () => dispatch({ type: "RESET" }),
    }
  }, [state])
}
