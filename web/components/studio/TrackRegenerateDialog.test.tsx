import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useEffect, useRef, useState } from "react"

import { TrackRegenerateDialog } from "./TrackRegenerateDialog"
import { StudioProvider, useStudio } from "@/contexts/studio-context"
import type { TrackType } from "@/lib/track-types"

type Route = {
  match: (url: string, method: string) => boolean
  status: number
  body: unknown
}

function stubFetch(routes: Route[]) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      const route = routes.find((r) => r.match(url, method))
      if (!route) return new Response("{}", { status: 404 })
      return new Response(JSON.stringify(route.body), { status: route.status })
    })
  )
  return calls
}

const happyRoutes = (clip: Record<string, unknown>): Route[] => [
  {
    match: (u, m) => u === "/api/generate" && m === "POST",
    status: 202,
    body: { job_id: "j1", estimated_time_seconds: 5 },
  },
  {
    match: (u) => u.startsWith("/api/jobs/j1"),
    status: 200,
    body: { status: "completed", clip_ids: [String(clip.id)] },
  },
  {
    match: (u) => u === `/api/clips/${clip.id}`,
    status: 200,
    body: clip,
  },
]

type SeedClip = { clipId: string; startSec: number; duration: number }

function Harness({
  trackType = "ai",
  clips = [],
}: {
  trackType?: TrackType
  clips?: SeedClip[]
}) {
  return (
    <StudioProvider>
      <Seed trackType={trackType} clips={clips} />
    </StudioProvider>
  )
}

function Seed({ trackType, clips }: { trackType: TrackType; clips: SeedClip[] }) {
  const { state, dispatch } = useStudio()
  const [open, setOpen] = useState(true)
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    dispatch({ type: "ADD_TRACK", id: "t1", trackType, name: "Track 1" })
    clips.forEach((c, i) => {
      dispatch({
        type: "ADD_CLIP",
        id: `seed-${i}`,
        trackId: "t1",
        clipId: c.clipId,
        startSec: c.startSec,
        title: "Seed",
        durationSec: c.duration,
        generationMode: trackType === "loop" ? "sound" : "song",
      })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const track = state.tracks.find((t) => t.id === "t1")
  if (!track) return null
  return (
    <>
      {open && (
        <TrackRegenerateDialog
          track={track}
          token="tok"
          onClose={() => setOpen(false)}
        />
      )}
      <div data-testid="clips-probe">
        {JSON.stringify(
          track.clips.map((c) => ({ clipId: c.clipId, startSec: c.startSec }))
        )}
      </div>
    </>
  )
}

const clipsProbe = () =>
  JSON.parse(screen.getByTestId("clips-probe").textContent!) as {
    clipId: string
    startSec: number
  }[]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("TrackRegenerateDialog", () => {
  it("submits the prompt and appends the generated clip after the track's last clip", async () => {
    const calls = stubFetch(
      happyRoutes({
        id: "nc1",
        title: "Regen",
        duration: 6,
        bpm: null,
        generation_mode: "song",
      })
    )
    const user = userEvent.setup()
    render(<Harness clips={[{ clipId: "c1", startSec: 0, duration: 4 }]} />)

    await user.type(
      screen.getByRole("textbox", { name: "Prompt" }),
      "dreamy synth chorus"
    )
    await user.click(screen.getByRole("button", { name: "Generate" }))

    await waitFor(() =>
      expect(clipsProbe()).toEqual([
        { clipId: "c1", startSec: 0 },
        { clipId: "nc1", startSec: 4 },
      ])
    )
    const gen = calls.find((c) => c.url === "/api/generate")!
    expect(gen.body).toMatchObject({ prompt: "dreamy synth chorus" })
    // Success closes the dialog.
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
  })

  it("requests sound/loop mode for a loop track so the clip can land on it", async () => {
    const calls = stubFetch(
      happyRoutes({
        id: "nc2",
        title: "Loop",
        duration: 8,
        bpm: 120,
        generation_mode: "sound",
      })
    )
    const user = userEvent.setup()
    render(<Harness trackType="loop" />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "drum loop")
    await user.click(screen.getByRole("button", { name: "Generate" }))

    await waitFor(() =>
      expect(clipsProbe()).toEqual([{ clipId: "nc2", startSec: 0 }])
    )
    const gen = calls.find((c) => c.url === "/api/generate")!
    expect(gen.body).toMatchObject({
      mode: "sound",
      sound_type: "loop",
      instrumental: true,
    })
  })

  it("sends instrumental=true when the Instrumental switch is on", async () => {
    const calls = stubFetch(
      happyRoutes({
        id: "nc3",
        title: "Inst",
        duration: 6,
        bpm: null,
        generation_mode: "song",
      })
    )
    const user = userEvent.setup()
    render(<Harness />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "ambient pad")
    await user.click(screen.getByRole("switch", { name: "Instrumental" }))
    await user.click(screen.getByRole("button", { name: "Generate" }))

    await waitFor(() =>
      expect(calls.find((c) => c.url === "/api/generate")).toBeTruthy()
    )
    expect(calls.find((c) => c.url === "/api/generate")!.body).toMatchObject({
      instrumental: true,
    })
  })

  it("shows the failure and keeps the dialog open when generation errors", async () => {
    stubFetch([
      {
        match: (u, m) => u === "/api/generate" && m === "POST",
        status: 500,
        body: { detail: "backend exploded" },
      },
    ])
    const user = userEvent.setup()
    render(<Harness />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "anything")
    await user.click(screen.getByRole("button", { name: "Generate" }))

    expect(await screen.findByText("backend exploded")).toBeInTheDocument()
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(clipsProbe()).toEqual([])
  })

  it("surfaces an error with a retry when the generated clip can't be fetched", async () => {
    // Generation succeeds, but the follow-up clip-metadata fetch 500s once and
    // then recovers — the dialog must show the failure (not hang on "Adding
    // clip…") and Retry must complete the add.
    let clipFetches = 0
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === "/api/generate" && init?.method === "POST") {
          return new Response(
            JSON.stringify({ job_id: "j1", estimated_time_seconds: 5 }),
            { status: 202 }
          )
        }
        if (url.startsWith("/api/jobs/j1")) {
          return new Response(
            JSON.stringify({ status: "completed", clip_ids: ["nc9"] }),
            { status: 200 }
          )
        }
        if (url === "/api/clips/nc9") {
          clipFetches += 1
          if (clipFetches === 1) return new Response("{}", { status: 500 })
          return new Response(
            JSON.stringify({
              id: "nc9",
              title: "Recovered",
              duration: 6,
              bpm: null,
              generation_mode: "song",
            }),
            { status: 200 }
          )
        }
        return new Response("{}", { status: 404 })
      })
    )
    const user = userEvent.setup()
    render(<Harness />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "anything")
    await user.click(screen.getByRole("button", { name: "Generate" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn.t be added/i
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(clipsProbe()).toEqual([])

    await user.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() =>
      expect(clipsProbe()).toEqual([{ clipId: "nc9", startSec: 0 }])
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
  })

  it("treats a generated clip whose type mismatches the track as a failure, not a silent close", async () => {
    // A loop track receiving a clip whose generation_mode infers as "ai":
    // ADD_CLIP would silently reject it, so the dialog must show the failure
    // instead of closing over a spent credit and a missing clip.
    stubFetch(
      happyRoutes({
        id: "nc4",
        title: "Wrong type",
        duration: 6,
        bpm: null,
        generation_mode: null,
      })
    )
    const user = userEvent.setup()
    render(<Harness trackType="loop" />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "drum loop")
    await user.click(screen.getByRole("button", { name: "Generate" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn.t be added/i
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(clipsProbe()).toEqual([])
  })

  it("ignores a second Retry click while an add is already in flight", async () => {
    let clipFetches = 0
    let resolveSecond: (r: Response) => void = () => {}
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === "/api/generate" && init?.method === "POST") {
          return new Response(
            JSON.stringify({ job_id: "j1", estimated_time_seconds: 5 }),
            { status: 202 }
          )
        }
        if (url.startsWith("/api/jobs/j1")) {
          return new Response(
            JSON.stringify({ status: "completed", clip_ids: ["nc5"] }),
            { status: 200 }
          )
        }
        if (url === "/api/clips/nc5") {
          clipFetches += 1
          if (clipFetches === 1) return new Response("{}", { status: 500 })
          // Second fetch hangs until we resolve it — the window for a
          // double-click.
          return new Promise<Response>((res) => {
            resolveSecond = res
          })
        }
        return new Response("{}", { status: 404 })
      })
    )
    const user = userEvent.setup()
    render(<Harness />)

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "anything")
    await user.click(screen.getByRole("button", { name: "Generate" }))
    await screen.findByRole("alert")

    const retry = screen.getByRole("button", { name: "Retry" })
    await user.click(retry)
    await user.click(retry) // double-click while the first retry is in flight
    expect(clipFetches).toBe(2) // 1 failed + 1 in flight — not 3

    resolveSecond(
      new Response(
        JSON.stringify({
          id: "nc5",
          title: "Recovered",
          duration: 6,
          bpm: null,
          generation_mode: "song",
        }),
        { status: 200 }
      )
    )
    await waitFor(() =>
      expect(clipsProbe()).toEqual([{ clipId: "nc5", startSec: 0 }])
    )
  })

  it("disables Generate until a prompt is entered", () => {
    stubFetch([])
    render(<Harness />)
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled()
  })
})
