import { renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { usePlayReport } from "@/hooks/use-play-report"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function setup() {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal("fetch", fetchMock)
  const { result } = renderHook(() => usePlayReport())
  const playThrough = (clipId: string, from: number, to: number) => {
    for (let t = from; t <= to; t += 0.25) result.current(clipId, t)
  }
  return { fetchMock, report: result.current, playThrough }
}

const plays = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith("/play"))
    .map(([url]) => url)

describe("usePlayReport (#656)", () => {
  it("reports once a clip has played for 30 seconds, and only once", () => {
    const { fetchMock, playThrough } = setup()
    playThrough("c1", 0, 29.5)
    expect(plays(fetchMock)).toEqual([])

    playThrough("c1", 29.75, 90)

    expect(plays(fetchMock)).toEqual(["/api/clips/c1/play"])
  })

  it("doesn't count a seek past the 30 second mark as listening", () => {
    const { fetchMock, report, playThrough } = setup()
    playThrough("c1", 0, 5)
    report("c1", 45)
    playThrough("c1", 45.25, 60)

    expect(plays(fetchMock)).toEqual([])
  })

  it("keeps counting across a loop back to the start", () => {
    const { fetchMock, playThrough } = setup()
    playThrough("c1", 0, 20)
    playThrough("c1", 0, 12)

    expect(plays(fetchMock)).toEqual(["/api/clips/c1/play"])
  })

  it("starts the count again for the next clip", () => {
    const { fetchMock, playThrough } = setup()
    playThrough("c1", 0, 20)
    playThrough("c2", 0, 20)
    expect(plays(fetchMock)).toEqual([])

    playThrough("c2", 20.25, 31)

    expect(plays(fetchMock)).toEqual(["/api/clips/c2/play"])
  })
})
