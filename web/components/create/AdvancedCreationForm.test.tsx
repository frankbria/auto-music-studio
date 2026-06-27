import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AdvancedCreationForm } from "@/components/create/AdvancedCreationForm"
import { STYLE_SUGGESTIONS } from "@/lib/profile"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

vi.mock("@/contexts/model-selection-context", () => ({
  useModelSelection: () => ({
    models: [{ key: "base", display_name: "Base" }],
    selectedModel: "base",
    isLoading: false,
  }),
}))

const submitAdvancedGeneration = vi.fn()
vi.mock("@/lib/generate", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/generate")>()
  return {
    ...actual,
    submitAdvancedGeneration: (...args: unknown[]) =>
      submitAdvancedGeneration(...args),
  }
})

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

function createButton() {
  return screen.getByRole("button", { name: /^create$/i })
}

describe("AdvancedCreationForm", () => {
  it("renders the lyrics panel with structure-tag placeholder and a vocal language selector", () => {
    render(<AdvancedCreationForm />)
    expect(screen.getByPlaceholderText(/\[Verse 1\]/)).toBeInTheDocument()
    expect(
      screen.getByRole("combobox", { name: /vocal language/i })
    ).toBeInTheDocument()
  })

  it("keeps Create disabled until there is a style or lyrics", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    expect(createButton()).toBeDisabled()
    await user.type(screen.getByLabelText("Styles"), "rock")
    expect(createButton()).toBeEnabled()
  })

  it("lets style pills and the styles textarea both contribute", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    await user.type(screen.getByLabelText("Styles"), "cinematic")

    const pill = screen
      .getAllByRole("button")
      .find((b) =>
        (STYLE_SUGGESTIONS as readonly string[]).includes(
          b.textContent?.trim() ?? ""
        )
      )
    expect(pill).toBeDefined()
    await user.click(pill!)
    expect(screen.getByLabelText("Selected tags")).toBeInTheDocument()
  })

  it("expands and collapses the More Options section", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    const toggle = screen.getByRole("button", { name: /more options/i })
    // The panel is always in the DOM (so aria-controls resolves) but hidden when
    // collapsed; assert visibility rather than presence.
    expect(screen.getByLabelText("BPM")).not.toBeVisible()
    await user.click(toggle)
    expect(screen.getByLabelText("BPM")).toBeVisible()
    expect(screen.getByLabelText(/weirdness/i)).toBeVisible()
    await user.click(toggle)
    expect(screen.getByLabelText("BPM")).not.toBeVisible()
  })

  it("restores the styles field after Clear via Undo", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    const styles = screen.getByLabelText("Styles")
    await user.type(styles, "rock")

    const stylesSection = screen.getByRole("region", { name: "Styles panel" })
    await user.click(
      within(stylesSection).getByRole("button", { name: /clear/i })
    )
    expect(styles).toHaveValue("")

    // Undo pops the empty entry pushed by Clear, restoring the prior text.
    await user.click(
      within(stylesSection).getByRole("button", { name: /undo/i })
    )
    expect(screen.getByLabelText("Styles")).toHaveValue("rock")
  })

  it("validates BPM range before submitting", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    await user.type(screen.getByLabelText("Styles"), "rock")
    await user.click(screen.getByRole("button", { name: /more options/i }))
    await user.click(screen.getByRole("switch", { name: "Auto" })) // turn Auto off
    await user.type(screen.getByLabelText("BPM"), "300")
    await user.click(createButton())

    expect(screen.getByRole("alert")).toHaveTextContent(/bpm/i)
    expect(submitAdvancedGeneration).not.toHaveBeenCalled()
  })

  it("submits a valid form, polls, and surfaces the completed clips", async () => {
    submitAdvancedGeneration.mockResolvedValue({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 20,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["c1", "c2"],
    })
    const onGenerated = vi.fn()
    const user = userEvent.setup()
    render(<AdvancedCreationForm onGenerated={onGenerated} />)
    await user.type(screen.getByLabelText("Styles"), "orchestral")
    await user.click(createButton())

    expect(submitAdvancedGeneration).toHaveBeenCalledWith(
      expect.objectContaining({ styles: "orchestral" }),
      "tok",
      "base"
    )
    expect(await screen.findByText(/clips are ready/i)).toBeInTheDocument()
    expect(onGenerated).toHaveBeenCalledOnce()
  })

  it("shows a model-aware estimate while polling and recovers via Retry", async () => {
    submitAdvancedGeneration.mockResolvedValue({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 45,
    })
    fetchJobStatus.mockResolvedValueOnce({
      kind: "failed",
      error: "Generation failed.",
    })
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    await user.type(screen.getByLabelText("Styles"), "orchestral")
    await user.click(createButton())

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Generation failed."
    )
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    await user.click(screen.getByRole("button", { name: /retry/i }))
    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent(/Base/)
    expect(status).toHaveTextContent(/~45s/)
  })

  it("Clear all resets the styles field", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    const styles = screen.getByLabelText("Styles")
    await user.type(styles, "orchestral")
    await user.click(screen.getByRole("button", { name: /clear all/i }))
    expect(screen.getByLabelText("Styles")).toHaveValue("")
    expect(createButton()).toBeDisabled()
  })

  it("shows the enhance input and a coming-soon notice on apply", async () => {
    const user = userEvent.setup()
    render(<AdvancedCreationForm />)
    await user.click(screen.getByRole("button", { name: /enhance/i }))
    await user.type(
      screen.getByLabelText(/enhancement prompt/i),
      "make it darker"
    )
    await user.click(screen.getByRole("button", { name: /apply/i }))
    expect(screen.getByRole("status")).toHaveTextContent(/coming soon/i)
  })
})
