import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AddAudioModal } from "@/components/create/modals/AddAudioModal"
import type { Clip } from "@/lib/workspace-clips"

const useClipsMock = vi.fn()
const useWorkspacesMock = vi.fn()

vi.mock("@/hooks/use-clips", () => ({
  useClips: (...args: unknown[]) => useClipsMock(...args),
}))
vi.mock("@/hooks/use-workspaces", () => ({
  useWorkspaces: () => useWorkspacesMock(),
}))

function clip(partial: Partial<Clip> & { id: string }): Clip {
  return {
    workspace_id: "w1",
    title: null,
    format: null,
    duration: 90,
    bpm: 120,
    key: null,
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: null,
    is_public: false,
    created_at: "2026-01-01",
    ...partial,
  }
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock")
  URL.revokeObjectURL = vi.fn()
  useWorkspacesMock.mockReturnValue({
    workspaces: [{ id: "w1", name: "My Workspace" }],
    defaultWorkspace: { id: "w1" },
  })
  useClipsMock.mockReturnValue({
    data: { clips: [clip({ id: "c1", title: "Sunset Drive" })] },
    loading: false,
  })
})

afterEach(() => vi.clearAllMocks())

describe("AddAudioModal", () => {
  it("opens with Remix, Upload, and Record tabs", () => {
    render(<AddAudioModal open onOpenChange={() => {}} onSelect={() => {}} />)
    expect(screen.getByRole("tab", { name: "Remix" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Upload" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Record" })).toBeInTheDocument()
  })

  it("selects a clip from the Remix tab", async () => {
    const onSelect = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    render(
      <AddAudioModal open onOpenChange={onOpenChange} onSelect={onSelect} />
    )

    await user.click(screen.getByRole("button", { name: /sunset drive/i }))
    expect(onSelect).toHaveBeenCalledWith({
      kind: "clip",
      clipId: "c1",
      label: "Sunset Drive",
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("validates and rejects an unsupported upload", async () => {
    const user = userEvent.setup()
    render(<AddAudioModal open onOpenChange={() => {}} onSelect={() => {}} />)

    await user.click(screen.getByRole("tab", { name: "Upload" }))
    // fireEvent bypasses the input's `accept` filter, exercising the JS
    // validation backstop that guards the drag-drop path.
    fireEvent.change(screen.getByLabelText("Upload audio file"), {
      target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] },
    })
    expect(screen.getByRole("alert")).toHaveTextContent(/unsupported/i)
  })

  it("previews and attaches a valid upload", async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<AddAudioModal open onOpenChange={() => {}} onSelect={onSelect} />)

    await user.click(screen.getByRole("tab", { name: "Upload" }))
    const file = new File(["x"], "loop.mp3", { type: "audio/mpeg" })
    await user.upload(screen.getByLabelText("Upload audio file"), file)

    expect(screen.getByLabelText("Preview loop.mp3")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /attach/i }))
    expect(onSelect).toHaveBeenCalledWith({
      kind: "upload",
      file,
      label: "loop.mp3",
    })
  })

  it("records via the microphone and uses the recording", async () => {
    const trackStop = vi.fn()
    const getUserMedia = vi
      .fn()
      .mockResolvedValue({ getTracks: () => [{ stop: trackStop }] })
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    })

    class FakeMediaRecorder {
      state = "inactive"
      ondataavailable: ((e: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = "recording"
      }
      stop() {
        this.state = "inactive"
        this.ondataavailable?.({ data: new Blob(["x"], { type: "audio/webm" }) })
        this.onstop?.()
      }
    }
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder)

    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<AddAudioModal open onOpenChange={() => {}} onSelect={onSelect} />)

    await user.click(screen.getByRole("tab", { name: "Record" }))
    await user.click(screen.getByRole("button", { name: /^record$/i }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument()
    )
    await user.click(screen.getByRole("button", { name: /stop/i }))

    await user.click(screen.getByRole("button", { name: /use recording/i }))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "record", label: "Recording" })
    )
    expect(trackStop).toHaveBeenCalled()
  })

  it("shows a permission-denied message when the mic is blocked", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new Error("denied")) },
    })
    const user = userEvent.setup()
    render(<AddAudioModal open onOpenChange={() => {}} onSelect={() => {}} />)

    await user.click(screen.getByRole("tab", { name: "Record" }))
    await user.click(screen.getByRole("button", { name: /^record$/i }))
    expect(await screen.findByRole("alert")).toHaveTextContent(/denied/i)
  })
})
