import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ModelSelectionProvider,
  useModelSelection,
} from "@/contexts/model-selection-context"

let auth: { accessToken: string | null; isLoading: boolean }
vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => auth,
}))

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const MODELS = [
  {
    key: "base",
    display_name: "Standard Model",
    category: "Standard",
    description: "Balanced",
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

function Probe() {
  const { selectedModel, isLoading, setSelectedModel } = useModelSelection()
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="selected">{selectedModel}</span>
      <button onClick={() => setSelectedModel("xl-base")}>pick-xl</button>
    </div>
  )
}

// Routes /api/models and /api/users/me; the profile call resolves only when
// `releaseProfile` is invoked, so we can observe the pre-seed window.
function routedFetch(profile: unknown) {
  let release: (() => void) | null = null
  const ready = new Promise<void>((r) => {
    release = r
  })
  const fetchMock = vi.fn(async (url: unknown) => {
    if (typeof url === "string" && url.includes("/api/models")) {
      return jsonRes({ models: MODELS })
    }
    await ready // gate the profile response
    return jsonRes(profile)
  })
  return { fetchMock, releaseProfile: () => release?.() }
}

afterEach(() => vi.restoreAllMocks())

describe("ModelSelectionProvider", () => {
  it("stays loading until the profile seed resolves, then applies the saved default", async () => {
    auth = { accessToken: "tok", isLoading: false }
    const { fetchMock, releaseProfile } = routedFetch({
      subscription_tier: "free",
      default_model: "xl-base",
    })
    vi.stubGlobal("fetch", fetchMock)

    render(
      <ModelSelectionProvider>
        <Probe />
      </ModelSelectionProvider>
    )

    // Before the profile resolves, the context must report loading so consumers
    // don't submit the provisional "base" over the user's saved default.
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("true")
    )

    releaseProfile()
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false")
    )
    expect(screen.getByTestId("selected")).toHaveTextContent("xl-base")
  })

  it("keeps a user's pick over a late-arriving saved default", async () => {
    auth = { accessToken: "tok", isLoading: false }
    const { fetchMock, releaseProfile } = routedFetch({
      subscription_tier: "free",
      default_model: "base",
    })
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()

    render(
      <ModelSelectionProvider>
        <Probe />
      </ModelSelectionProvider>
    )

    await user.click(await screen.findByRole("button", { name: "pick-xl" }))
    releaseProfile()
    // The profile default ("base") must not clobber the explicit pick.
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false")
    )
    expect(screen.getByTestId("selected")).toHaveTextContent("xl-base")
  })
})
