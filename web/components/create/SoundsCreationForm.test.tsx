import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SoundsCreationForm } from "@/components/create/SoundsCreationForm"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}))

vi.mock("@/contexts/model-selection-context", () => ({
  useModelSelection: () => ({ selectedModel: "base" }),
}))

// Stubbed so the unauthorized path's router.push("/login") never throws.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const submitSoundsGeneration = vi.fn()
vi.mock("@/lib/generate", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/generate")>()
  return {
    ...actual,
    submitSoundsGeneration: (...args: unknown[]) => submitSoundsGeneration(...args),
  }
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("SoundsCreationForm", () => {
  const createButton = () => screen.getByRole("button", { name: /^create$/i })
  const oneShot = () => screen.getByRole("button", { name: "One-Shot" })
  const loop = () => screen.getByRole("button", { name: "Loop" })

  it("disables Create until both a description and a type are chosen", async () => {
    const user = userEvent.setup()
    render(<SoundsCreationForm />)
    expect(createButton()).toBeDisabled()

    // Description alone is not enough — the type is required.
    await user.type(screen.getByLabelText("Sound description"), "a punchy kick")
    expect(createButton()).toBeDisabled()

    await user.click(oneShot())
    expect(createButton()).toBeEnabled()
  })

  it("shows BPM and key only for loops, not one-shots", async () => {
    const user = userEvent.setup()
    render(<SoundsCreationForm />)

    await user.click(oneShot())
    expect(screen.queryByLabelText("BPM")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Key")).not.toBeInTheDocument()

    await user.click(loop())
    expect(screen.getByLabelText("BPM")).toBeInTheDocument()
    expect(screen.getByLabelText("Key")).toBeInTheDocument()
  })

  it("submits a one-shot and reports success", async () => {
    submitSoundsGeneration.mockResolvedValue({ status: "accepted", jobId: "job-1" })
    const user = userEvent.setup()
    render(<SoundsCreationForm />)

    await user.type(screen.getByLabelText("Sound description"), "a punchy kick")
    await user.click(oneShot())
    await user.click(createButton())

    expect(submitSoundsGeneration).toHaveBeenCalledWith(
      expect.objectContaining({ description: "a punchy kick", soundType: "one-shot" }),
      "tok",
      "base"
    )
    expect(await screen.findByRole("status")).toHaveTextContent(/started/i)
  })

  it("sends loop tempo and key with the request", async () => {
    submitSoundsGeneration.mockResolvedValue({ status: "accepted", jobId: "job-2" })
    const user = userEvent.setup()
    render(<SoundsCreationForm />)

    await user.type(screen.getByLabelText("Sound description"), "a driving bass loop")
    await user.click(loop())
    await user.click(screen.getByRole("switch", { name: "Auto" })) // turn Auto off
    await user.type(screen.getByLabelText("BPM"), "128")
    await user.selectOptions(screen.getByLabelText("Key"), "A minor")
    await user.click(createButton())

    expect(submitSoundsGeneration).toHaveBeenCalledWith(
      expect.objectContaining({ soundType: "loop", bpm: "128", key: "A minor" }),
      "tok",
      "base"
    )
    // Guard the loop success-message branch separately from the one-shot one.
    expect(await screen.findByRole("status")).toHaveTextContent(/started/i)
  })

  it("surfaces an error notice when generation fails", async () => {
    submitSoundsGeneration.mockResolvedValue({ status: "error", detail: "Server error" })
    const user = userEvent.setup()
    render(<SoundsCreationForm />)

    await user.type(screen.getByLabelText("Sound description"), "a punchy kick")
    await user.click(oneShot())
    await user.click(createButton())

    expect(await screen.findByRole("alert")).toHaveTextContent(/server error/i)
  })
})
