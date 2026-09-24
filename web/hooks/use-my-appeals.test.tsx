import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useMyAppeals } from "@/hooks/use-my-appeals"
import type { AppealView } from "@/lib/appeals"

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }))
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const appeal: AppealView = {
  id: "a1",
  clip_id: "c1",
  action: "remove",
  reason: "not spam",
  context: null,
  status: "pending",
  admin_note: null,
  created_at: "2026-01-01T00:00:00Z",
  decided_at: null,
}

describe("useMyAppeals", () => {
  it("fetches the caller's appeals and maps them by clip id", async () => {
    stubFetch(200, { appeals: [appeal] })
    const { result } = renderHook(() => useMyAppeals("tok"))
    await waitFor(() => expect(result.current.appeals).toHaveLength(1))
    expect(result.current.byClip.get("c1")).toEqual(appeal)
  })

  it("never fetches without a token", () => {
    const fetchMock = stubFetch(200, { appeals: [appeal] })
    const { result } = renderHook(() => useMyAppeals(null))
    expect(result.current.appeals).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("refetch() re-runs the request", async () => {
    const fetchMock = stubFetch(200, { appeals: [] })
    const { result } = renderHook(() => useMyAppeals("tok"))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    result.current.refetch()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})
