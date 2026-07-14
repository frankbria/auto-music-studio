import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { act } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ExportMenu } from "./ExportMenu"
import { AuthContext } from "@/contexts/auth-context"
import { StudioProvider, useStudio } from "@/contexts/studio-context"
import type { StudioExportState } from "@/hooks/use-studio-export"

// --- Mock the export hook so the menu's wiring is tested deterministically;
// the submit→poll→download lifecycle has its own unit tests. ---
const exportMixdown = vi.fn()
const exportDaw = vi.fn()
const reset = vi.fn()
let hookState: StudioExportState = { phase: "idle" }
let capturedOnComplete: ((clipId: string | null) => void) | undefined

vi.mock("@/hooks/use-studio-export", () => ({
  useStudioExport: (opts?: {
    onMixdownComplete?: (clipId: string | null) => void
  }) => {
    capturedOnComplete = opts?.onMixdownComplete
    return { state: hookState, exportMixdown, exportDaw, reset }
  },
}))

vi.mock("@/hooks/use-workspaces", () => ({
  useWorkspaces: () => ({
    defaultWorkspace: { id: "w1", is_default: true },
    workspaces: [],
    loading: false,
    error: false,
  }),
}))

afterEach(() => {
  hookState = { phase: "idle" }
  capturedOnComplete = undefined
  vi.clearAllMocks()
})

const auth = {
  user: { id: "u1" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
} as never

/** Seeds one non-empty track so the studio has something to export. */
function Seed() {
  const { state, dispatch } = useStudio()
  if (state.tracks.length === 0) {
    dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
    dispatch({
      type: "ADD_CLIP",
      id: "pl1",
      trackId: "t1",
      clipId: "c1",
      startSec: 0,
      title: "Clip",
      durationSec: 10,
      generationMode: null,
    })
  }
  return null
}

function renderMenu(props: { onMixdownComplete?: () => void } = {}) {
  return render(
    <AuthContext.Provider value={auth}>
      <StudioProvider>
        <Seed />
        <ExportMenu {...props} />
      </StudioProvider>
    </AuthContext.Provider>
  )
}

describe("ExportMenu", () => {
  it("renders an export trigger", () => {
    renderMenu()
    expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument()
  })

  it("submits a WAV mixdown built from the studio arrangement", async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole("button", { name: /export/i }))
    await user.click(screen.getByRole("menuitem", { name: /wav/i }))

    expect(exportMixdown).toHaveBeenCalledOnce()
    const [body, token] = exportMixdown.mock.calls[0]
    expect(token).toBe("tok")
    expect(body.format).toBe("wav")
    expect(body.workspace_id).toBe("w1")
    expect(body.tracks).toHaveLength(1)
  })

  it("submits an MP3 mixdown when MP3 is chosen", async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole("button", { name: /export/i }))
    await user.click(screen.getByRole("menuitem", { name: /mp3/i }))
    expect(exportMixdown.mock.calls[0][0].format).toBe("mp3")
  })

  it("submits a DAW export bundle", async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole("button", { name: /export/i }))
    await user.click(screen.getByRole("menuitem", { name: /daw/i }))

    expect(exportDaw).toHaveBeenCalledOnce()
    const [body, token] = exportDaw.mock.calls[0]
    expect(token).toBe("tok")
    expect(body).not.toHaveProperty("format")
    expect(body.workspace_id).toBe("w1")
  })

  it("bumps the workspace refresh when a mixdown completes", () => {
    const onMixdownComplete = vi.fn()
    renderMenu({ onMixdownComplete })
    // Simulate the hook firing its completion callback.
    act(() => capturedOnComplete?.("mix1"))
    expect(onMixdownComplete).toHaveBeenCalledOnce()
  })

  it("shows inline progress while a job is running", () => {
    hookState = { phase: "polling", progress: "Mixing" }
    renderMenu()
    expect(screen.getByRole("status")).toHaveTextContent("Mixing")
  })

  it("shows an error message when an export fails", () => {
    hookState = { phase: "error", message: "Export failed. Please try again." }
    renderMenu()
    expect(screen.getByRole("status")).toHaveTextContent(/failed/i)
  })
})
