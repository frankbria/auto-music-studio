import { render } from "@testing-library/react"
import { act } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useEffect, useRef } from "react"

import { useStudioPlayback } from "./use-studio-playback"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import { StudioProvider, useStudio } from "@/contexts/studio-context"
import {
  DEFAULT_MASTER_BUS,
  LIMITER_ATTACK_SEC,
  LIMITER_RATIO,
} from "@/lib/master-bus"
import { dbToGain } from "@/lib/track-audio"
import type { TrackType } from "@/lib/track-types"

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

class FakePannerNode {
  connect = vi.fn()
  disconnect = vi.fn()
  pan = { value: 0 }
}

class FakeBiquadFilterNode {
  type: BiquadFilterType = "lowpass"
  connect = vi.fn()
  disconnect = vi.fn()
  frequency = { value: 350 }
  gain = { value: 0 }
  Q = { value: 1 }
}

class FakeDynamicsCompressorNode {
  connect = vi.fn()
  disconnect = vi.fn()
  threshold = { value: -24 }
  knee = { value: 30 }
  ratio = { value: 12 }
  attack = { value: 0.003 }
  release = { value: 0.25 }
  reduction = 0
}

class FakeChannelSplitterNode {
  connect = vi.fn()
  disconnect = vi.fn()
}

class FakeAnalyserNode {
  connect = vi.fn()
  disconnect = vi.fn()
  fftSize = 2048
  getFloatTimeDomainData = vi.fn()
}

class FakeSourceNode {
  buffer: AudioBuffer | null = null
  playbackRate = { value: 1 }
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
  // gains[0] is always the master gain; per-track gains follow (US-19.4);
  // the master bus's own volume gain is appended after them, once (US-19.5).
  const gains: FakeGainNode[] = []
  const panners: FakePannerNode[] = []
  const biquads: FakeBiquadFilterNode[] = []
  const compressors: FakeDynamicsCompressorNode[] = []
  const splitters: FakeChannelSplitterNode[] = []
  const analysers: FakeAnalyserNode[] = []
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
    createGain = vi.fn(() => {
      const g = new FakeGainNode()
      gains.push(g)
      return g
    })
    createStereoPanner = vi.fn(() => {
      const p = new FakePannerNode()
      panners.push(p)
      return p
    })
    createBufferSource = vi.fn(() => {
      const s = new FakeSourceNode()
      sources.push(s)
      return s
    })
    createBiquadFilter = vi.fn(() => {
      const f = new FakeBiquadFilterNode()
      biquads.push(f)
      return f
    })
    createDynamicsCompressor = vi.fn(() => {
      const c = new FakeDynamicsCompressorNode()
      compressors.push(c)
      return c
    })
    createChannelSplitter = vi.fn(() => {
      const s = new FakeChannelSplitterNode()
      splitters.push(s)
      return s
    })
    createAnalyser = vi.fn(() => {
      const a = new FakeAnalyserNode()
      analysers.push(a)
      return a
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
  return { sources, gains, panners, biquads, compressors, splitters, analysers, box }
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
  trackId?: string
  generationMode?: string | null
  clipBpm?: number | null
}

type SeedTrack = { id: string; trackType: TrackType }

const DEFAULT_TRACKS: SeedTrack[] = [{ id: "t1", trackType: "ai" }]

function Harness({
  token = "tok",
  clips = [],
  tracks = DEFAULT_TRACKS,
  autoplay = false,
}: {
  token?: string | null
  clips?: SeedClip[]
  tracks?: SeedTrack[]
  autoplay?: boolean
}) {
  return (
    <PlayerProvider>
      <StudioProvider>
        <Seed token={token} clips={clips} tracks={tracks} autoplay={autoplay} />
      </StudioProvider>
    </PlayerProvider>
  )
}

function Seed({
  token,
  clips,
  tracks,
  autoplay,
}: {
  token: string | null
  clips: SeedClip[]
  tracks: SeedTrack[]
  autoplay: boolean
}) {
  const { state: studioState, dispatch } = useStudio()
  const { state: playerState } = usePlayer()
  const seededRef = useRef(false)

  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    for (const t of tracks) {
      dispatch({ type: "ADD_TRACK", id: t.id, trackType: t.trackType })
    }
    clips.forEach((c, i) => {
      dispatch({
        type: "ADD_CLIP",
        id: `p${i}`,
        trackId: c.trackId ?? "t1",
        clipId: c.clipId,
        startSec: c.startSec,
        title: c.title,
        durationSec: c.duration,
        generationMode: c.generationMode,
        clipBpm: c.clipBpm,
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

  it("plays clips on the same track sequentially by timeline position (US-19.2 acceptance)", async () => {
    const { sources, box } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          clips={[
            { clipId: "c1", title: "A", duration: 4, startSec: 0 },
            { clipId: "c2", title: "B", duration: 4, startSec: 4 },
          ]}
          autoplay
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    const now = box.instance!.currentTime
    expect(sources).toHaveLength(2)
    // One after the other: the second starts exactly when the first ends.
    expect(sources[0].start).toHaveBeenCalledWith(now, 0)
    expect(sources[1].start).toHaveBeenCalledWith(now + 4, 0)
  })

  it("plays clips on different tracks simultaneously (US-19.2 acceptance)", async () => {
    const { sources, box } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 4,
    })

    await act(async () => {
      render(
        <Harness
          tracks={[
            { id: "t1", trackType: "ai" },
            { id: "t2", trackType: "ai" },
          ]}
          clips={[
            { clipId: "c1", title: "A", duration: 4, startSec: 0, trackId: "t1" },
            { clipId: "c2", title: "B", duration: 4, startSec: 0, trackId: "t2" },
          ]}
          autoplay
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    const now = box.instance!.currentTime
    expect(sources).toHaveLength(2)
    // Same start time on both sources: layered playback.
    expect(sources[0].start).toHaveBeenCalledWith(now, 0)
    expect(sources[1].start).toHaveBeenCalledWith(now, 0)
  })

  it("applies the loop track's tempo-derived playback rate to the source (US-19.2)", async () => {
    const { sources } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 8,
    })

    await act(async () => {
      render(
        <Harness
          tracks={[{ id: "t1", trackType: "loop" }]}
          clips={[
            {
              clipId: "c1",
              title: "Loop",
              duration: 8,
              startSec: 0,
              generationMode: "sound",
              clipBpm: 90,
            },
          ]}
          autoplay
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(sources).toHaveLength(1)
    // 90 BPM loop in the default 120 BPM project → 4/3 rate.
    expect(sources[0].playbackRate.value).toBeCloseTo(4 / 3)
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
        dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
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
        dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
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

describe("useStudioPlayback loop region (US-19.3)", () => {
  function LoopSeed({
    loop,
    startAtSec,
  }: {
    loop: { startSec: number; endSec: number }
    startAtSec?: number
  }) {
    const { state, dispatch } = useStudio()
    const seededRef = useRef(false)
    useEffect(() => {
      if (seededRef.current) return
      seededRef.current = true
      dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
      dispatch({
        type: "ADD_CLIP",
        id: "p0",
        trackId: "t1",
        clipId: "c1",
        startSec: 0,
        title: "A",
        durationSec: 100,
      })
      dispatch({ type: "SET_LOOP_REGION", ...loop })
      dispatch({ type: "TOGGLE_LOOP" })
      if (startAtSec != null) dispatch({ type: "SEEK", sec: startAtSec })
      dispatch({ type: "SET_PLAYING", playing: true })
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    useStudioPlayback("tok")
    return <div data-testid="playhead-probe">{state.playheadSec}</div>
  }

  function LoopHarness(props: {
    loop: { startSec: number; endSec: number }
    startAtSec?: number
  }) {
    return (
      <PlayerProvider>
        <StudioProvider>
          <LoopSeed {...props} />
        </StudioProvider>
      </PlayerProvider>
    )
  }

  it("wraps the playhead back to loop start when it reaches loop end, rescheduling audio", async () => {
    const { sources, box } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 100,
    })

    const { getByTestId } = render(
      <LoopHarness loop={{ startSec: 2, endSec: 4 }} />
    )
    await act(async () => {
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)

    // Playback crosses the loop end (4s): the tick must seek back to 2s...
    await act(async () => {
      box.instance!.currentTime = 4.5
      raf.tick(4500)
      await Promise.resolve()
    })
    expect(getByTestId("playhead-probe")).toHaveTextContent(/^2$/)

    // ...and the seekEpoch bump reschedules audio from the loop start.
    expect(sources[0].stop).toHaveBeenCalled()
    expect(sources).toHaveLength(2)
    expect(sources[1].start).toHaveBeenCalledWith(4.5, 2)
  })

  it("plays straight through the loop region when the run starts past its end", async () => {
    const { sources, box } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: fakeBuffer(),
      peaks: new Float32Array(),
      duration: 100,
    })

    const { getByTestId } = render(
      <LoopHarness loop={{ startSec: 2, endSec: 4 }} startAtSec={5} />
    )
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      box.instance!.currentTime = 1
      raf.tick(1000)
      await Promise.resolve()
    })
    expect(getByTestId("playhead-probe")).toHaveTextContent(/^6$/)
    expect(sources).toHaveLength(1)
  })
})

describe("useStudioPlayback per-track controls (US-19.4)", () => {
  function ControlsSeed({
    setup = [],
  }: {
    setup?: import("@/contexts/studio-context").StudioAction[]
  }) {
    const { dispatch } = useStudio()
    const seededRef = useRef(false)
    useEffect(() => {
      if (seededRef.current) return
      seededRef.current = true
      dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
      dispatch({ type: "ADD_TRACK", id: "t2", trackType: "ai" })
      dispatch({
        type: "ADD_CLIP",
        id: "p0",
        trackId: "t1",
        clipId: "c1",
        startSec: 0,
        title: "A",
        durationSec: 100,
      })
      dispatch({
        type: "ADD_CLIP",
        id: "p1",
        trackId: "t2",
        clipId: "c2",
        startSec: 0,
        title: "B",
        durationSec: 100,
      })
      for (const a of setup) dispatch(a)
      dispatch({ type: "SET_PLAYING", playing: true })
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    useStudioPlayback("tok")
    return (
      <>
        <button onClick={() => dispatch({ type: "SET_TRACK_VOLUME", trackId: "t1", volumeDb: -6 })}>
          duck t1
        </button>
        <button onClick={() => dispatch({ type: "SET_TRACK_PAN", trackId: "t1", pan: -100 })}>
          pan t1 left
        </button>
        <button onClick={() => dispatch({ type: "TOGGLE_TRACK_MUTE", trackId: "t1" })}>
          mute t1
        </button>
        <button onClick={() => dispatch({ type: "TOGGLE_TRACK_SOLO", trackId: "t2" })}>
          solo t2
        </button>
      </>
    )
  }

  function ControlsHarness(props: {
    setup?: import("@/contexts/studio-context").StudioAction[]
  }) {
    return (
      <PlayerProvider>
        <StudioProvider>
          <ControlsSeed {...props} />
        </StudioProvider>
      </PlayerProvider>
    )
  }

  const audio = {
    buffer: fakeBuffer(),
    peaks: new Float32Array(),
    duration: 100,
  }

  it("routes each source through its own track's gain → panner → master chain", async () => {
    const { sources, gains, panners } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    await act(async () => {
      render(<ControlsHarness />)
      await Promise.resolve()
      await Promise.resolve()
    })

    // gains[0] = master sum; then one gain+panner per track, in track order;
    // gains[3] = the master bus's own volume gain, appended once it's built
    // after the per-track loop (US-19.5) — appending after preserves every
    // other index this and sibling tests rely on.
    expect(gains).toHaveLength(4)
    expect(panners).toHaveLength(2)
    expect(sources).toHaveLength(2)
    expect(sources[0].connect).toHaveBeenCalledWith(gains[1])
    expect(sources[1].connect).toHaveBeenCalledWith(gains[2])
    expect(gains[1].connect).toHaveBeenCalledWith(panners[0])
    expect(panners[0].connect).toHaveBeenCalledWith(gains[0])
  })

  it("initializes gain and pan from the track's volume/pan state", async () => {
    const { gains, panners } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    await act(async () => {
      render(
        <ControlsHarness
          setup={[
            { type: "SET_TRACK_VOLUME", trackId: "t1", volumeDb: -6 },
            { type: "SET_TRACK_PAN", trackId: "t1", pan: 50 },
          ]}
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(gains[1].gain.value).toBeCloseTo(0.501, 2)
    expect(panners[0].pan.value).toBeCloseTo(0.5)
    // t2 untouched: unity gain, centered.
    expect(gains[2].gain.value).toBe(1)
    expect(panners[1].pan.value).toBe(0)
  })

  it("schedules a muted track at zero gain, and solo silences non-soloed tracks", async () => {
    const { gains } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    await act(async () => {
      render(
        <ControlsHarness
          setup={[
            { type: "TOGGLE_TRACK_MUTE", trackId: "t1" },
            { type: "TOGGLE_TRACK_SOLO", trackId: "t2" },
          ]}
        />
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(gains[1].gain.value).toBe(0) // muted (and not soloed)
    expect(gains[2].gain.value).toBe(1) // soloed
  })

  it("live-updates volume, pan, mute, and solo mid-playback without rescheduling sources", async () => {
    const { sources, gains, panners } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    const { getByRole } = render(<ControlsHarness />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(sources).toHaveLength(2)
    expect(gains[1].gain.value).toBe(1)

    await act(async () => {
      getByRole("button", { name: "duck t1" }).click()
      getByRole("button", { name: "pan t1 left" }).click()
    })
    expect(gains[1].gain.value).toBeCloseTo(0.501, 2)
    expect(panners[0].pan.value).toBe(-1)

    await act(async () => {
      getByRole("button", { name: "solo t2" }).click()
    })
    // t1 is now implicitly silenced by t2's solo; t2 keeps its own gain.
    expect(gains[1].gain.value).toBe(0)
    expect(gains[2].gain.value).toBe(1)

    await act(async () => {
      getByRole("button", { name: "solo t2" }).click() // un-solo
      getByRole("button", { name: "mute t1" }).click()
    })
    expect(gains[1].gain.value).toBe(0) // muted
    expect(gains[2].gain.value).toBe(1)

    // The whole point: none of the above tore down or restarted audio.
    expect(sources).toHaveLength(2)
    expect(sources[0].stop).not.toHaveBeenCalled()
    expect(sources[1].stop).not.toHaveBeenCalled()
  })
})

describe("useStudioPlayback master bus (US-19.5)", () => {
  function MasterBusSeed() {
    const { dispatch } = useStudio()
    const seededRef = useRef(false)
    useEffect(() => {
      if (seededRef.current) return
      seededRef.current = true
      dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
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
    const { analyserLeft, analyserRight, limiter } = useStudioPlayback("tok")
    return (
      <>
        <div data-testid="analyser-left-probe">
          {analyserLeft.current ? "ready" : "null"}
        </div>
        <div data-testid="analyser-right-probe">
          {analyserRight.current ? "ready" : "null"}
        </div>
        <div data-testid="limiter-probe">
          {limiter.current ? "ready" : "null"}
        </div>
        <button
          onClick={() =>
            dispatch({ type: "SET_MASTER_VOLUME", volumeDb: -12 })
          }
        >
          set master volume
        </button>
        <button
          onClick={() =>
            dispatch({
              type: "SET_MASTER_EQ",
              band: "low",
              freqHz: 60,
              gainDb: 4,
            })
          }
        >
          set low eq
        </button>
        <button
          onClick={() =>
            dispatch({
              type: "SET_MASTER_EQ",
              band: "mid",
              freqHz: 2000,
              gainDb: -3,
              q: 2,
            })
          }
        >
          set mid eq
        </button>
        <button
          onClick={() =>
            dispatch({
              type: "SET_MASTER_EQ",
              band: "high",
              freqHz: 6000,
              gainDb: 5,
            })
          }
        >
          set high eq
        </button>
        <button
          onClick={() =>
            dispatch({
              type: "SET_MASTER_COMPRESSOR",
              thresholdDb: -10,
              ratio: 6,
              attackSec: 0.05,
              releaseSec: 0.2,
            })
          }
        >
          set compressor
        </button>
        <button
          onClick={() =>
            dispatch({ type: "SET_MASTER_LIMITER_CEILING", ceilingDb: -1 })
          }
        >
          set limiter ceiling
        </button>
      </>
    )
  }

  function MasterBusHarness() {
    return (
      <PlayerProvider>
        <StudioProvider>
          <MasterBusSeed />
        </StudioProvider>
      </PlayerProvider>
    )
  }

  const audio = { buffer: fakeBuffer(), peaks: new Float32Array(), duration: 100 }

  it("wires the master chain sum → EQ → compressor → limiter → masterVolume → destination + analysers", async () => {
    const { gains, biquads, compressors, splitters, analysers } =
      stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    await act(async () => {
      render(<MasterBusHarness />)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(biquads).toHaveLength(3)
    const [lowShelf, midPeak, highShelf] = biquads
    expect(lowShelf.type).toBe("lowshelf")
    expect(midPeak.type).toBe("peaking")
    expect(highShelf.type).toBe("highshelf")

    expect(compressors).toHaveLength(2)
    const [compressor, limiter] = compressors

    expect(splitters).toHaveLength(1)
    expect(analysers).toHaveLength(2)
    const [analyserLeft, analyserRight] = analysers

    const sum = gains[0]
    const masterVolume = gains[gains.length - 1]

    expect(sum.connect).toHaveBeenCalledWith(lowShelf)
    expect(lowShelf.connect).toHaveBeenCalledWith(midPeak)
    expect(midPeak.connect).toHaveBeenCalledWith(highShelf)
    expect(highShelf.connect).toHaveBeenCalledWith(compressor)
    expect(compressor.connect).toHaveBeenCalledWith(limiter)
    expect(limiter.connect).toHaveBeenCalledWith(masterVolume)
    expect(masterVolume.connect).toHaveBeenCalledWith(splitters[0])
    expect(splitters[0].connect).toHaveBeenCalledWith(analyserLeft, 0)
    expect(splitters[0].connect).toHaveBeenCalledWith(analyserRight, 1)
  })

  it("only builds the master chain once across repeated play runs", async () => {
    const { biquads } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    function ReplaySeed() {
      const { dispatch } = useStudio()
      const seededRef = useRef(false)
      useEffect(() => {
        if (seededRef.current) return
        seededRef.current = true
        dispatch({ type: "ADD_TRACK", id: "t1", trackType: "ai" })
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
        <button onClick={() => dispatch({ type: "SEEK", sec: 5 })}>
          seek
        </button>
      )
    }

    const { getByRole } = render(
      <PlayerProvider>
        <StudioProvider>
          <ReplaySeed />
        </StudioProvider>
      </PlayerProvider>
    )
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(biquads).toHaveLength(3)

    await act(async () => {
      getByRole("button", { name: "seek" }).click()
      await Promise.resolve()
      await Promise.resolve()
    })
    // A seek reschedules per-track nodes but must not rebuild the master
    // chain a second time.
    expect(biquads).toHaveLength(3)
  })

  it("initializes chain params from DEFAULT_MASTER_BUS at build time", async () => {
    const { gains, biquads, compressors } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    await act(async () => {
      render(<MasterBusHarness />)
      await Promise.resolve()
      await Promise.resolve()
    })

    const [lowShelf, midPeak, highShelf] = biquads
    expect(lowShelf.frequency.value).toBe(DEFAULT_MASTER_BUS.eq.lowShelf.freqHz)
    expect(lowShelf.gain.value).toBe(DEFAULT_MASTER_BUS.eq.lowShelf.gainDb)
    expect(midPeak.frequency.value).toBe(DEFAULT_MASTER_BUS.eq.midPeak.freqHz)
    expect(midPeak.Q.value).toBe(DEFAULT_MASTER_BUS.eq.midPeak.q)
    expect(highShelf.frequency.value).toBe(
      DEFAULT_MASTER_BUS.eq.highShelf.freqHz
    )

    const [compressor, limiter] = compressors
    expect(compressor.threshold.value).toBe(
      DEFAULT_MASTER_BUS.compressor.thresholdDb
    )
    expect(compressor.ratio.value).toBe(DEFAULT_MASTER_BUS.compressor.ratio)
    expect(compressor.attack.value).toBe(
      DEFAULT_MASTER_BUS.compressor.attackSec
    )
    expect(compressor.release.value).toBe(
      DEFAULT_MASTER_BUS.compressor.releaseSec
    )

    // Limiter ratio/attack are fixed constants, not driven by user state.
    expect(limiter.ratio.value).toBe(LIMITER_RATIO)
    expect(limiter.attack.value).toBeCloseTo(LIMITER_ATTACK_SEC)
    expect(limiter.threshold.value).toBe(DEFAULT_MASTER_BUS.limiterCeilingDb)

    const masterVolume = gains[gains.length - 1]
    expect(masterVolume.gain.value).toBeCloseTo(
      dbToGain(DEFAULT_MASTER_BUS.masterVolumeDb)
    )
  })

  it("exposes analyser and limiter refs once the chain is built", async () => {
    const { box } = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    const { getByTestId } = render(<MasterBusHarness />)
    expect(getByTestId("analyser-left-probe")).toHaveTextContent("null")
    expect(getByTestId("limiter-probe")).toHaveTextContent("null")

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // The ref itself is already populated by this point — refs don't trigger
    // a re-render on mutation, so force one (a rAF tick dispatches
    // SET_PLAYHEAD) to observe it reflected in the DOM.
    act(() => {
      box.instance!.currentTime = 1
      raf.tick(1000)
    })

    expect(getByTestId("analyser-left-probe")).toHaveTextContent("ready")
    expect(getByTestId("analyser-right-probe")).toHaveTextContent("ready")
    expect(getByTestId("limiter-probe")).toHaveTextContent("ready")
  })

  it("live-retunes master volume without rescheduling sources", async () => {
    const { sources, gains } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    const { getByRole } = render(<MasterBusHarness />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(sources).toHaveLength(1)
    const masterVolume = gains[gains.length - 1]
    expect(masterVolume.gain.value).toBeCloseTo(1)

    await act(async () => {
      getByRole("button", { name: "set master volume" }).click()
    })
    expect(masterVolume.gain.value).toBeCloseTo(dbToGain(-12))
    expect(sources).toHaveLength(1)
    expect(sources[0].stop).not.toHaveBeenCalled()
  })

  it("live-retunes EQ bands without rescheduling sources", async () => {
    const { sources, biquads } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    const { getByRole } = render(<MasterBusHarness />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    const [lowShelf, midPeak, highShelf] = biquads

    await act(async () => {
      getByRole("button", { name: "set low eq" }).click()
      getByRole("button", { name: "set mid eq" }).click()
      getByRole("button", { name: "set high eq" }).click()
    })

    expect(lowShelf.frequency.value).toBe(60)
    expect(lowShelf.gain.value).toBe(4)
    expect(midPeak.frequency.value).toBe(2000)
    expect(midPeak.gain.value).toBe(-3)
    expect(midPeak.Q.value).toBe(2)
    expect(highShelf.frequency.value).toBe(6000)
    expect(highShelf.gain.value).toBe(5)

    expect(sources).toHaveLength(1)
    expect(sources[0].stop).not.toHaveBeenCalled()
  })

  it("live-retunes the compressor and limiter ceiling without rescheduling sources", async () => {
    const { sources, compressors } = stubAudioContext()
    stubRaf()
    getClipAudioMock.mockResolvedValue(audio)

    const { getByRole } = render(<MasterBusHarness />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    const [compressor, limiter] = compressors

    await act(async () => {
      getByRole("button", { name: "set compressor" }).click()
      getByRole("button", { name: "set limiter ceiling" }).click()
    })

    expect(compressor.threshold.value).toBe(-10)
    expect(compressor.ratio.value).toBe(6)
    expect(compressor.attack.value).toBe(0.05)
    expect(compressor.release.value).toBe(0.2)
    expect(limiter.threshold.value).toBe(-1)
    // Ratio/attack remain fixed even after a limiter-ceiling change.
    expect(limiter.ratio.value).toBe(LIMITER_RATIO)
    expect(limiter.attack.value).toBeCloseTo(LIMITER_ATTACK_SEC)

    expect(sources).toHaveLength(1)
    expect(sources[0].stop).not.toHaveBeenCalled()
  })
})
