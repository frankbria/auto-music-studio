import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SectionGenerationStep } from "@/components/song/full-song/SectionGenerationStep"
import type { Section } from "@/lib/song-structure"

const submitExtend = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitExtend: (...args: unknown[]) => submitExtend(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

const section: Section = {
  name: "intro",
  durationSeconds: 15.6,
  styleHint: "intro, atmospheric build, sparse arrangement",
}

function renderStep(props: Partial<React.ComponentProps<typeof SectionGenerationStep>> = {}) {
  const onComplete = vi.fn()
  render(
    <SectionGenerationStep
      cumulativeClipId="cum-0"
      section={section}
      baseStyle="lofi"
      instructions=""
      accessToken="tok"
      sectionNumber={1}
      totalSections={7}
      onComplete={onComplete}
      {...props}
    />
  )
  return { onComplete }
}

describe("SectionGenerationStep", () => {
  it("extends the cumulative clip with the section duration + composed style, then reports the new clip", async () => {
    submitExtend.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["gen-1"] })

    const { onComplete } = renderStep()

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("gen-1"))
    expect(submitExtend).toHaveBeenCalledWith(
      "cum-0",
      {
        duration: "15s", // 15.6 floored
        from_point: "end",
        style_override: "lofi, intro, atmospheric build, sparse arrangement",
      },
      "tok"
    )
  })

  it("folds regeneration instructions into the style override", async () => {
    submitExtend.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["gen-1"] })

    renderStep({ instructions: "more energy" })

    await waitFor(() => expect(submitExtend).toHaveBeenCalled())
    expect(submitExtend.mock.calls[0][1].style_override).toBe(
      "lofi, intro, atmospheric build, sparse arrangement, more energy"
    )
  })

  it("surfaces an error with a Retry when generation can't be afforded", async () => {
    submitExtend.mockResolvedValue({ status: "insufficientCredits", balance: 0, required: 1 })

    const { onComplete } = renderStep()

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/not enough credits/i)
    )
    expect(onComplete).not.toHaveBeenCalled()

    // Retry re-issues the extend.
    submitExtend.mockResolvedValue({ status: "accepted", jobId: "j2", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["gen-2"] })
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("gen-2"))
  })
})
