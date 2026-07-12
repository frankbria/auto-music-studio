import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { useEffect, useRef } from "react"

import { TransportControls } from "./TransportControls"
import { StudioProvider, useStudio } from "@/contexts/studio-context"

/** Seeds a nonzero playhead/isPlaying state before rendering, so reset/pause
 * behavior has something to observe. */
function Harness({
  initialPlayheadSec = 0,
  initialPlaying = false,
}: {
  initialPlayheadSec?: number
  initialPlaying?: boolean
}) {
  return (
    <StudioProvider>
      <Seed
        initialPlayheadSec={initialPlayheadSec}
        initialPlaying={initialPlaying}
      >
        <TransportControls />
      </Seed>
    </StudioProvider>
  )
}

function Seed({
  initialPlayheadSec,
  initialPlaying,
  children,
}: {
  initialPlayheadSec: number
  initialPlaying: boolean
  children: React.ReactNode
}) {
  const { state, dispatch } = useStudio()
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    dispatch({ type: "SET_PLAYHEAD", sec: initialPlayheadSec })
    dispatch({ type: "SET_PLAYING", playing: initialPlaying })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      {children}
      <div data-testid="playhead-probe">{state.playheadSec}</div>
      <div data-testid="playing-probe">{String(state.isPlaying)}</div>
    </>
  )
}

describe("TransportControls play/pause", () => {
  it("shows Play when paused and Pause when playing", async () => {
    render(<Harness />)
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Play" }))
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument()
    expect(screen.getByTestId("playing-probe")).toHaveTextContent("true")
  })

  it("pausing does not reset the playhead", async () => {
    render(<Harness initialPlayheadSec={12} initialPlaying={true} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Pause" }))
    expect(screen.getByTestId("playing-probe")).toHaveTextContent("false")
    expect(screen.getByTestId("playhead-probe")).toHaveTextContent("12")
  })
})

describe("TransportControls stop", () => {
  it("stops playback and resets the playhead to 0", async () => {
    render(<Harness initialPlayheadSec={20} initialPlaying={true} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Stop" }))
    expect(screen.getByTestId("playing-probe")).toHaveTextContent("false")
    expect(screen.getByTestId("playhead-probe")).toHaveTextContent("0")
  })
})

describe("TransportControls return to start", () => {
  it("resets the playhead without changing play state", async () => {
    render(<Harness initialPlayheadSec={20} initialPlaying={true} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Return to start" }))
    expect(screen.getByTestId("playhead-probe")).toHaveTextContent("0")
    expect(screen.getByTestId("playing-probe")).toHaveTextContent("true")
  })
})
