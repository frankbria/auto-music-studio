import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  NotificationsProvider,
  useNotify,
} from "@/contexts/notifications-context"
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
    expect(result.current.byClip.get("c1")).toEqual([appeal])
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

  it("refetches when a moderation notice arrives, not on other notices (#543)", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ appeals: [] }))
    )
    vi.stubGlobal("fetch", fetchMock)
    const { result } = renderHook(
      () => ({ appeals: useMyAppeals("tok"), notify: useNotify() }),
      { wrapper: NotificationsProvider }
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    act(() =>
      result.current.notify({
        type: "mastering_complete",
        message: "m",
        href: "/",
      })
    )
    act(() =>
      result.current.notify({
        type: "moderation",
        message: "Appeal approved",
        href: "/",
      })
    )

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
