import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ClipMultiSelector } from "@/components/song/modals/ClipMultiSelector"
import { MASHUP_CLIPS_MAX } from "@/lib/constants/editing"
import { makeClip } from "@/test/clip-factory"

const useClips = vi.fn()
vi.mock("@/hooks/use-clips", () => ({
  useClips: (...args: unknown[]) => useClips(...args),
}))

afterEach(() => vi.clearAllMocks())

function mockClips(clips: ReturnType<typeof makeClip>[]) {
  useClips.mockReturnValue({ data: { clips }, loading: false, error: false })
}

describe("ClipMultiSelector", () => {
  it("hides clips that are not WAV with duration", () => {
    mockClips([
      makeClip({ id: "wav-1", title: "Keeper" }),
      makeClip({ id: "mp3-1", title: "Wrong format", format: "mp3" }),
      makeClip({ id: "no-dur", title: "No duration", duration: null }),
    ])
    render(<ClipMultiSelector workspaceId="ws-1" selected={[]} onChange={vi.fn()} />)

    expect(screen.getByText("Keeper")).toBeInTheDocument()
    expect(screen.queryByText("Wrong format")).not.toBeInTheDocument()
    expect(screen.queryByText("No duration")).not.toBeInTheDocument()
  })

  it("shows a loading state while fetching", () => {
    useClips.mockReturnValue({ data: null, loading: true, error: false })
    render(<ClipMultiSelector workspaceId="ws-1" selected={[]} onChange={vi.fn()} />)
    expect(screen.getByText("Loading clips…")).toBeInTheDocument()
  })

  it("shows an empty state when no clips are eligible", () => {
    mockClips([makeClip({ id: "mp3-1", format: "mp3" })])
    render(<ClipMultiSelector workspaceId="ws-1" selected={[]} onChange={vi.fn()} />)
    expect(screen.getByText("No eligible clips to mash up.")).toBeInTheDocument()
  })

  it("toggles a clip's id through onChange, preserving order", async () => {
    const onChange = vi.fn()
    mockClips([
      makeClip({ id: "a", title: "Alpha" }),
      makeClip({ id: "b", title: "Beta" }),
    ])
    render(<ClipMultiSelector workspaceId="ws-1" selected={["a"]} onChange={onChange} />)

    await userEvent.click(screen.getByRole("checkbox", { name: /Beta/ }))
    expect(onChange).toHaveBeenCalledWith(["a", "b"])
  })

  it("removes a clip's id when unchecked", async () => {
    const onChange = vi.fn()
    mockClips([makeClip({ id: "a", title: "Alpha" })])
    render(<ClipMultiSelector workspaceId="ws-1" selected={["a"]} onChange={onChange} />)

    await userEvent.click(screen.getByRole("checkbox", { name: /Alpha/ }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it("prunes a pre-seeded selection id that is not eligible", async () => {
    const onChange = vi.fn()
    // "a" is eligible; the seeded "ghost" clip is not in the eligible list.
    mockClips([makeClip({ id: "a", title: "Alpha" })])
    render(
      <ClipMultiSelector
        workspaceId="ws-1"
        selected={["ghost", "a"]}
        onChange={onChange}
      />
    )
    // The ineligible id is dropped so it can't be submitted invisibly.
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith(["a"]))
  })

  it("disables unselected clips once the max is reached", () => {
    const clips = Array.from({ length: MASHUP_CLIPS_MAX + 1 }, (_, i) =>
      makeClip({ id: `c${i}`, title: `Clip ${i}` })
    )
    mockClips(clips)
    const selected = clips.slice(0, MASHUP_CLIPS_MAX).map((c) => c.id)
    render(<ClipMultiSelector workspaceId="ws-1" selected={selected} onChange={vi.fn()} />)

    // The one clip past the cap that is not selected must be disabled.
    const overflow = screen.getByRole("checkbox", { name: /Clip 8/ })
    expect(overflow).toBeDisabled()
    // Selected ones stay enabled so they can be removed.
    expect(screen.getByRole("checkbox", { name: /Clip 0/ })).toBeEnabled()
  })
})
