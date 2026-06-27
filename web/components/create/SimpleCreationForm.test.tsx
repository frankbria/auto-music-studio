import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SimpleCreationForm } from "@/components/create/SimpleCreationForm"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

vi.mock("@/contexts/model-selection-context", () => ({
  useModelSelection: () => ({ selectedModel: "base", isLoading: false }),
}))

const submitGeneration = vi.fn()
vi.mock("@/lib/generate", () => ({
  submitGeneration: (...args: unknown[]) => submitGeneration(...args),
}))

afterEach(() => {
  vi.clearAllMocks()
})

describe("SimpleCreationForm", () => {
  function createButton() {
    return screen.getByRole("button", { name: /create/i })
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

  it("submits the form state and reports success", async () => {
    submitGeneration.mockResolvedValue({ status: "accepted", jobId: "job-1" })
    const user = userEvent.setup()
    render(<SimpleCreationForm />)

    await user.type(screen.getByLabelText("Song description"), "dreamy")
    await user.click(screen.getByRole("switch", { name: "Instrumental" }))
    await user.click(createButton())

    expect(submitGeneration).toHaveBeenCalledWith(
      expect.objectContaining({ description: "dreamy", instrumental: true }),
      "tok",
      "base"
    )
    expect(await screen.findByRole("status")).toHaveTextContent(/started/i)
  })

  it("shows the +Audio placeholder as a neutral notice, not an error", async () => {
    const user = userEvent.setup()
    render(<SimpleCreationForm />)
    await user.click(screen.getByRole("button", { name: /audio/i }))
    expect(screen.getByRole("status")).toHaveTextContent(/coming soon/i)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})
