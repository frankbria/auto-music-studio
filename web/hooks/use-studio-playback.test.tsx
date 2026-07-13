import { render } from "@testing-library/react"
import { act } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useEffect, useRef } from "react"

import { useStudioPlayback } from "./use-studio-playback"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import { StudioProvider, useStudio } from "@/contexts/studio-context"

const { getClipAudioMock } = vi.hoisted(() => ({
  getClipAudioMock: vi.fn(),
}))
vi.mock("@/lib/clip-audio-cache", () => ({
  getClipAudio: getClipAudioMock,
}))

// --- Minimal Web Audio + rAF stand-ins (jsdom has neither) -----------------

function fakeBuffer(): AudioBuffer {
  return {} as unknown as AudioBuffer
}

class FakeGainNode {
  connect = vi.fn()
  disconnect = vi.fn()
  gain = { value: 1 }
}

class FakeSourceNode {
  buffer: AudioBuffer | null = null
  connect = vi.fn()
  disconnect = vi.fn()
  start = vi.fn()
  stop = vi.fn()
}

/** Installs a fake `AudioContext` global and returns the single instance the
 * hook will construct (via `instance`, populated on first `new`) plus every
 * buffer source it creates. `initialState` mimics a browser starting the
 * context "suspended" until resumed from a user gesture. */
function stubAudioContext(initialState: AudioContextState = "running") {
  const sources: FakeSourceNode[] = []
  const box: {
    instance: {
      currentTime: number
      state: AudioContextState
      resume: () => Promise<void>
    } | null
  } = { instance: null }
  class FakeAudioContext {
    currentTime = 0
    state: AudioContextState = initialState
    destination = {}
    createGain = vi.fn(() => new FakeGainNode())
    createBufferSource = vi.fn(() => {
      const s = new FakeSourceNode()
      sources.push(s)
      return s
    })
    resume = vi.fn(() => {
      this.state = "running"
      return Promise.resolve()
    })
    close = vi.fn().mockResolvedValue(undefined)
    constructor() {
      box.instance = this
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext)
  return { sources, box }
}

function stubRaf() {
  let nextId = 1
  const callbacks = new Map<number, FrameRequestCallback>()
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((cb: FrameRequestCallback) => {
      const id = nextId++
      callbacks.set(id, cb)
      return id
    })
  )
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => {
      callbacks.delete(id)
    })
  )
  return {
    /** Invoke every currently-scheduled rAF callback once, at time `t`. */
    tick(t: number) {
      const due = [...callbacks.entries()]
      callbacks.clear()
      for (const [, cb] of due) cb(t)
    },
  }
}

// --- Harness ----------------------------------------------------------------

type SeedClip = {
  clipId: string
  title: string
  duration: number
  startSec: number
}

function Harness({
  token = "tok",
  clips = [],
  autoplay = false,
}: {
  token?: string | null
  clips?: SeedClip[]
  autoplay?: boolean
}) {
  return (
    <PlayerProvider>
      <StudioProvider>
        <Seed token={token} clips={clips} autoplay={autoplay} />
      </StudioProvider>
    </PlayerProvider>
  )
}

function Seed({
  token,
  clips,
  autoplay,
}: {
  token: string | null
  clips: SeedClip[]
  autoplay: boolean
}) {
  const { state: studioState, dispatch } = useStudio()
  const { state: playerState } = usePlayer()
  const seededRef = useRef(false)

  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    dispatch({ type: "ADD_TRACK", id: "t1" })
    clips.forEach((c, i) => {
      dispatch({
        type: "ADD_CLIP",
        id: `p${i}`,
        trackId: "t1",
        clipId: c.clipId,
        startSec: c.startSec,
        title: c.title,
        durationSec: c.duration,
      })
    })
    if (autoplay) dispatch({ type: "SET_PLAYING", playing: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useStudioPlayback(token)

  return (
    <>
      <div data-testid="playhead-probe">{studioState.playheadSec}</div>
      <div data-testid="studio-playing-probe">
        {String(studioState.isPlaying)}
      </div>
      <div data-testid="player-playing-probe">
        {String(playerState.isPlaying)}
      </div>
    </>
  )
}

afterEach(() => {
  getClipAudioMock.mockReset()
  vi.unstubAllGlobals()
})

describe("useStudioPlayback scheduling", () => {
  it("schedules a buffer source per placement when playback starts", async () => {
    const { sources } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          clips={[{ clipId: "c1", title: "A", duration: 4, startSec: 0 }]}
          autoplay
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(getClipAudioMock).toHaveBeenCalledWith("c1", "tok")
    expect(sources).toHaveLength(1)
    expect(sources[0].start).toHaveBeenCalled()
    expect(sources[0].connect).toHaveBeenCalled()
  })

  it("does not schedule anything without a token", async () => {
    stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          token={null}
          clips={[{ clipId: "c1", title: "A", duration: 4, startSec: 0 }]}
          autoplay
        />
      )
    })

    expect(getClipAudioMock).not.toHaveBeenCalled()
  })
})

describe("useStudioPlayback playhead timing vs. decode", () => {
  it("does not advance the playhead while buffers are still decoding", async () => {
    const { sources, box } = stubAudioContext()
    const raf = stubRaf()
    let resolveDecode: (a: unknown) => void = () => {}
    getClipAudioMock.mockReturnValue(
      new Promise((res) => {
        resolveDecode = res
      })
    )

    const { getByTestId } = render(
      <Harness
        clips={[{ clipId: "c1", title: "A", duration: 100, startSec: 0 }]}
        autoplay
      />
    )
    await act(async () => {
      await Promise.resolve()
    })

    // Decode is still in flight: nothing scheduled yet, and — critically —
    // no rAF tick was even registered, so firing one is a no-op and the
    // playhead must not have moved despite 5s of "AudioContext time" passing.
    expect(sources).toHaveLength(0)
    box.instance!.currentTime = 5
    act(() => raf.tick(5000))
    expect(sources).toHaveLength(0)
    expect(getByTestId("playhead-probe")).toHaveTextContent("0")

    // Decode resolves: only now do sources start and the tick loop begin.
    await act(async () => {
      resolveDecode({
        buffer: fakeBuffer(),
        peaks: new Float32Array(),
        duration: 100,
      })
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)
    expect(sources[0].start).toHaveBeenCalled()
  })

  it("origins the rAF loop from ctx.currentTime read after decode, not before it", async () => {
    const { box } = stubAudioContext()
    const raf = stubRaf()
    let resolveDecode: (a: unknown) => void = () => {}
    getClipAudioMock.mockReturnValue(
      new Promise((res) => {
        resolveDecode = res
      })
    )

    const { getByTestId } = render(
      <Harness
        clips={[{ clipId: "c1", title: "A", duration: 100, startSec: 0 }]}
        autoplay
      />
    )
    await act(async () => {
      await Promise.resolve()
    })

    // 3s of AudioContext time passes while the buffer is still decoding.
    box.instance!.currentTime = 3

    await act(async () => {
      resolveDecode({
        buffer: fakeBuffer(),
        peaks: new Float32Array(),
        duration: 100,
      })
      await Promise.resolve()
    })

    // One more second passes, then the tick fires. If the origin had been
    // captured before decode (at ctx.currentTime=0), this would report 4s
    // elapsed instead of the correct 1s.
    act(() => {
      box.instance!.currentTime = 4
      raf.tick(4000)
    })
    expect(getByTestId("playhead-probe")).toHaveTextContent("1")
  })
})

describe("useStudioPlayback decode failure", () => {
  it("stops playback (visibly) when a clip's decode rejects, without starting any source or ticking", async () => {
    const { sources } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockImplementation((clipId: string) =>
      clipId === "c1"
        ? Promise.resolve({
            buffer: fakeBuffer(),
            peaks: new Float32Array(),
            duration: 4,
          })
        : Promise.reject(new Error("404"))
    )

    const { getByTestId } = render(
      <Harness
        clips={[
          { clipId: "c1", title: "A", duration: 4, startSec: 0 },
          { clipId: "c2", title: "B", duration: 4, startSec: 0 },
        ]}
        autoplay
      />
    )
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(getByTestId("studio-playing-probe")).toHaveTextContent("false")
    expect(sources).toHaveLength(0)

    // No tick was ever scheduled, so firing one is a no-op — the playhead
    // must not have moved either.
    act(() => raf.tick(1000))
    expect(getByTestId("playhead-probe")).toHaveTextContent("0")
  })
})

describe("useStudioPlayback AudioContext resume", () => {
  it("resumes a context that starts suspended (browsers create it suspended outside a user gesture)", async () => {
    const { box } = stubAudioContext("suspended")
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          clips={[{ clipId: "c1", title: "A", duration: 4, startSec: 0 }]}
          autoplay
        />
      )
      await Promise.resolve()
    })

    expect(box.instance!.resume).toHaveBeenCalled()
  })

  it("does not call resume when the context is already running", async () => {
    const { box } = stubAudioContext("running")
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          clips={[{ clipId: "c1", title: "A", duration: 4, startSec: 0 }]}
          autoplay
        />
      )
      await Promise.resolve()
    })

    expect(box.instance!.resume).not.toHaveBeenCalled()
  })
})

describe("useStudioPlayback global player silencing", () => {
  it("pauses the global playbar when studio playback starts", async () => {
    stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    const { getByTestId } = render(<Harness autoplay />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(getByTestId("player-playing-probe")).toHaveTextContent("false")
  })
})

describe("useStudioPlayback rAF playhead loop", () => {
  it("advances SET_PLAYHEAD as AudioContext time passes", async () => {
    const { box } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 100,
    })

    const { getByTestId } = render(
      <Harness
        clips={[{ clipId: "c1", title: "A", duration: 100, startSec: 0 }]}
        autoplay
      />
    )
    await act(async () => {
      await Promise.resolve()
    })
    expect(getByTestId("playhead-probe")).toHaveTextContent("0")

    // Advance the fake AudioContext's clock by 2s, then fire the rAF tick —
    // the playhead should follow ctx.currentTime, not wall-clock time.
    act(() => {
      box.instance!.currentTime = 2
      raf.tick(2000)
    })
    expect(getByTestId("playhead-probe")).toHaveTextContent("2")
  })
})

describe("useStudioPlayback seek during playback", () => {
  it("stops the old source and reschedules a new one from the seek position on a seekEpoch bump", async () => {
    const { sources } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 100,
    })

    function SeekHarness() {
      const { dispatch } = useStudio()
      useEffect(() => {
        dispatch({ type: "ADD_TRACK", id: "t1" })
        dispatch({
          type: "ADD_CLIP",
          id: "p0",
          trackId: "t1",
          clipId: "c1",
          startSec: 0,
          title: "A",
          durationSec: 100,
        })
        dispatch({ type: "SET_PLAYING", playing: true })
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [])
      useStudioPlayback("tok")
      return (
        <button onClick={() => dispatch({ type: "SEEK", sec: 10 })}>
          seek
        </button>
      )
    }

    const { getByRole } = render(
      <PlayerProvider>
        <StudioProvider>
          <SeekHarness />
        </StudioProvider>
      </PlayerProvider>
    )
    await act(async () => {
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)
    const original = sources[0]

    await act(async () => {
      getByRole("button", { name: "seek" }).click()
      await Promise.resolve()
    })

    expect(original.stop).toHaveBeenCalled()
    expect(sources).toHaveLength(2)
    // The new source starts at the seeked-to offset (10s into a clip
    // starting at 0s), not the stale pre-seek position.
    expect(sources[1].start).toHaveBeenCalledWith(0, 10)
  })

  it("does not bump seekEpoch — and so does not reschedule — for the rAF loop's own SET_PLAYHEAD ticks", async () => {
    const { sources, box } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 100,
    })

    render(
      <Harness
        clips={[{ clipId: "c1", title: "A", duration: 100, startSec: 0 }]}
        autoplay
      />
    )
    await act(async () => {
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)

    act(() => {
      box.instance!.currentTime = 2
      raf.tick(2000)
    })

    // The rAF loop's own playhead tick must not itself trigger a reschedule.
    expect(sources).toHaveLength(1)
    expect(sources[0].stop).not.toHaveBeenCalled()
  })
})

describe("useStudioPlayback cleanup", () => {
  it("stops active sources when playback is paused", async () => {
    const { sources } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    function ToggleHarness() {
      const { dispatch } = useStudio()
      useEffect(() => {
        dispatch({ type: "ADD_TRACK", id: "t1" })
        dispatch({
          type: "ADD_CLIP",
          id: "p0",
          trackId: "t1",
          clipId: "c1",
          startSec: 0,
          title: "A",
          durationSec: 4,
        })
        dispatch({ type: "SET_PLAYING", playing: true })
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [])
      useStudioPlayback("tok")
      return (
        <button
          onClick={() => dispatch({ type: "SET_PLAYING", playing: false })}
        >
          pause
        </button>
      )
    }

    const { getByRole } = render(
      <PlayerProvider>
        <StudioProvider>
          <ToggleHarness />
        </StudioProvider>
      </PlayerProvider>
    )
    await act(async () => {
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)

    await act(async () => {
      getByRole("button", { name: "pause" }).click()
    })
    expect(sources[0].stop).toHaveBeenCalled()
  })
})
