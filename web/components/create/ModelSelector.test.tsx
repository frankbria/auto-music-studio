import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ModelSelector } from "@/components/create/ModelSelector"
import type { ModelInfo } from "@/lib/models"

const setSelectedModel = vi.fn()
let ctx: {
  models: ModelInfo[]
  selectedModel: string
  setSelectedModel: typeof setSelectedModel
  subscriptionTier: string
  isLoading: boolean
}

vi.mock("@/contexts/model-selection-context", () => ({
  useModelSelection: () => ctx,
}))

const MODELS: ModelInfo[] = [
  {
    key: "base",
    display_name: "Standard Model",
    category: "Standard",
    description: "Balanced quality/speed",
    pro_only: false,
    vram: "~2.4GB",
    steps: "32-64",
    dit_size: "2B",
  },
  {
    key: "xl-base",
    display_name: "Latest Model (XL)",
    category: "XL",
    description: "Highest quality",
    pro_only: true,
    vram: "~8GB",
    steps: "32-64",
    dit_size: "4B",
  },
]

function setCtx(overrides: Partial<typeof ctx> = {}) {
  ctx = {
    models: MODELS,
    selectedModel: "base",
    setSelectedModel,
    subscriptionTier: "free",
    isLoading: false,
    ...overrides,
  }
}

afterEach(() => {
  vi.clearAllMocks()
})

describe("ModelSelector", () => {
  it("shows the selected model's display name on the trigger", () => {
    setCtx({ selectedModel: "xl-base" })
    render(<ModelSelector />)
    expect(
      screen.getByTestId("model-selector-trigger")
    ).toHaveTextContent("Latest Model (XL)")
  })

  it("lists models with a Pro badge on pro-only options", async () => {
    setCtx()
    const user = userEvent.setup()
    render(<ModelSelector />)

    await user.click(screen.getByTestId("model-selector-trigger"))
    expect(screen.getByTestId("model-option-base")).toBeInTheDocument()
    const pro = screen.getByTestId("model-option-xl-base")
    expect(pro).toHaveTextContent("Pro")
    // Free-tier users still see (and can select) Pro models — display only.
    expect(pro).not.toBeDisabled()
  })

  it("selecting a model calls setSelectedModel with its key", async () => {
    setCtx()
    const user = userEvent.setup()
    render(<ModelSelector />)

    await user.click(screen.getByTestId("model-selector-trigger"))
    await user.click(screen.getByTestId("model-option-xl-base"))
    expect(setSelectedModel).toHaveBeenCalledWith("xl-base")
  })

  it("renders an empty state when no models are available", async () => {
    setCtx({ models: [] })
    const user = userEvent.setup()
    render(<ModelSelector />)

    await user.click(screen.getByTestId("model-selector-trigger"))
    expect(screen.getByText(/no models available/i)).toBeInTheDocument()
  })
})
