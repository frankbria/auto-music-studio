import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SimpleCreationForm } from "@/components/create/SimpleCreationForm"

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

const submitGeneration = vi.fn()
vi.mock("@/lib/generate", () => ({
  submitGeneration: (...args: unknown[]) => submitGeneration(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => {
  vi.clearAllMocks()
})

describe("SimpleCreationForm", () => {
  function createButton() {
    return screen.getByRole("button", { name: /^creat/i })
  }

  it("disables Create when description and lyrics are both empty", () => {
    render(<SimpleCreationForm />)
    expect(createButton()).toBeDisabled()
  })

  it("enables Create once the description has content", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    await user.type(
      screen.getByLabelText("Song description"),
      "a calm piano piece"
    )
    expect(createButton()).toBeEnabled()
  })

  it("reveals the lyrics textarea and enables Create from lyrics alone", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    expect(screen.queryByLabelText("Lyrics")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /lyrics/i }))
    const lyrics = screen.getByLabelText("Lyrics")
    expect(lyrics).toBeInTheDocument()

    await user.type(lyrics, "la la la")
    expect(createButton()).toBeEnabled()
  })

  it("disables Create again when lyrics are hidden after being the only input", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)

    await user.click(screen.getByRole("button", { name: /lyrics/i }))
    await user.type(screen.getByLabelText("Lyrics"), "la la la")
    expect(createButton()).toBeEnabled()

    // Hiding the lyrics field must not leave Create enabled on hidden text.
    await user.click(screen.getByRole("button", { name: /lyrics/i }))
    expect(createButton()).toBeDisabled()
  })

  it("toggles the instrumental switch", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    const toggle = screen.getByRole("switch", { name: "Instrumental" })
    expect(toggle).toHaveAttribute("aria-checked", "false")
    await user.click(toggle)
    expect(toggle).toHaveAttribute("aria-checked", "true")
  })

  it("submits, polls, and surfaces the completed clips", async () => {
    submitGeneration.mockResolvedValue({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 5,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["c1", "c2"],
    })
    const onGenerated = vi.fn()
    const user = userEvent.setup()
    render(<SimpleCreationForm onGenerated={onGenerated} />)

    await user.type(screen.getByLabelText("Song description"), "dreamy")
    await user.click(screen.getByRole("switch", { name: "Instrumental" }))
    await user.click(createButton())

    expect(submitGeneration).toHaveBeenCalledWith(
      expect.objectContaining({ description: "dreamy", instrumental: true }),
      "tok",
      "base"
    )
    expect(await screen.findByText(/clips are ready/i)).toBeInTheDocument()
    expect(onGenerated).toHaveBeenCalledOnce()
  })

  it("shows a model-aware time estimate while generating", async () => {
    submitGeneration.mockResolvedValue({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 30,
    })
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    const user = userEvent.setup()
    render(<SimpleCreationForm />)

    await user.type(screen.getByLabelText("Song description"), "dreamy")
    await user.click(createButton())

    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent(/Base/)
    expect(status).toHaveTextContent(/~30s/)
  })

  it("shows an error with a working Retry when the job fails", async () => {
    submitGeneration.mockResolvedValue({
      status: "accepted",
      jobId: "job-1",
      estimatedSeconds: 5,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "failed",
      error: "Generation failed.",
    })
    const user = userEvent.setup()
    render(<SimpleCreationForm />)

    await user.type(screen.getByLabelText("Song description"), "dreamy")
    await user.click(createButton())

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Generation failed."
    )
    await user.click(screen.getByRole("button", { name: /retry/i }))
    await waitFor(() => expect(submitGeneration).toHaveBeenCalledTimes(2))
  })

  it("Clear all resets the form fields", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    const description = screen.getByLabelText("Song description")
    await user.type(description, "dreamy")
    expect(description).toHaveValue("dreamy")

    await user.click(screen.getByRole("button", { name: /clear all/i }))
    expect(screen.getByLabelText("Song description")).toHaveValue("")
    expect(createButton()).toBeDisabled()
  })

  it("shows the +Audio placeholder as a neutral notice, not an error", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    await user.click(screen.getByRole("button", { name: /audio/i }))
    expect(screen.getByRole("status")).toHaveTextContent(/coming soon/i)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})
