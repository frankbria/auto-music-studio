import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useStudioExport } from "@/hooks/use-studio-export"
import type { MixdownRequestBody, StudioExportBody } from "@/lib/studio-export"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const mixdownBody: MixdownRequestBody = {
  workspace_id: "w1",
  project_name: "Song",
  bpm: 120,
  markers: [],
  tracks: [],
  format: "wav",
}
const dawBody: StudioExportBody = {
  workspace_id: "w1",
  project_name: "Song",
  bpm: 120,
  markers: [],
  tracks: [],
}

describe("useStudioExport — mixdown", () => {
  it("submits, polls, and surfaces the resulting clip id, calling onMixdownComplete", async () => {
    const onMixdownComplete = vi.fn()
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ job_id: "j1" }), { status: 202 })
        )
    )
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["mix1"] })

    const { result } = renderHook(() => useStudioExport({ onMixdownComplete }))
    await act(async () => {
      await result.current.exportMixdown(mixdownBody, "tok")
    })

    await waitFor(() =>
      expect(result.current.state.phase).toBe("success")
    )
    expect(result.current.state).toEqual({ phase: "success", clipId: "mix1" })
    expect(onMixdownComplete).toHaveBeenCalledWith("mix1")
    expect(fetchJobStatus).toHaveBeenCalledWith("j1", "tok")
  })

  it("posts the body to the mixdown endpoint with the bearer token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ job_id: "j1" }), { status: 202 })
      )
    vi.stubGlobal("fetch", fetchMock)
    fetchJobStatus.mockResolvedValue({ kind: "pending", progress: "Mixing" })

    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportMixdown(mixdownBody, "tok")
    })

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/studio/mixdown")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body).format).toBe("wav")
    expect(result.current.state).toMatchObject({
      phase: "polling",
      progress: "Mixing",
    })
    act(() => result.current.reset())
  })

  it("surfaces a failed job as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ job_id: "j1" }), { status: 202 })
        )
    )
    fetchJobStatus.mockResolvedValue({ kind: "failed", error: "boom" })

    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportMixdown(mixdownBody, "tok")
    })

    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "error", message: "boom" })
    )
  })

  it("surfaces a rejected submission as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "bad" }), { status: 422 })
        )
    )
    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportMixdown(mixdownBody, "tok")
    })
    expect(result.current.state.phase).toBe("error")
  })

  it("redirects to login on a 401 submission", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 }))
    )
    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportMixdown(mixdownBody, "tok")
    })
    expect(push).toHaveBeenCalledWith("/login")
  })
})

describe("useStudioExport — DAW", () => {
  it("downloads the ZIP bundle when the job completes and reaches success", async () => {
    const click = vi.fn()
    const anchor = { href: "", download: "", click } as unknown as HTMLAnchorElement
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, "createElement").mockImplementation((tag: string) =>
      tag === "a" ? anchor : realCreate(tag)
    )
    const createObjectURL = vi.fn(() => "blob:zip")
    const revokeObjectURL = vi.fn()
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL

    const fetchMock = vi
      .fn()
      // 1. POST /api/studio/export/daw → 202
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: "j9" }), { status: 202 })
      )
      // 2. GET the ZIP bundle
      .mockResolvedValueOnce(
        new Response("PKzip", {
          status: 200,
          headers: {
            "content-type": "application/zip",
            "content-disposition": 'attachment; filename="My_Song_Export.zip"',
          },
        })
      )
    vi.stubGlobal("fetch", fetchMock)
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: [] })

    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportDaw(dawBody, "tok")
    })

    await waitFor(() => expect(result.current.state.phase).toBe("success"))
    expect(fetchMock.mock.calls[0][0]).toBe("/api/studio/export/daw")
    expect(fetchMock.mock.calls[1][0]).toBe("/api/studio/export/daw/j9")
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:zip")
  })

  it("surfaces a failed bundle download as an error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: "j9" }), { status: 202 })
      )
      .mockResolvedValueOnce(new Response("nope", { status: 500 }))
    vi.stubGlobal("fetch", fetchMock)
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: [] })

    const { result } = renderHook(() => useStudioExport())
    await act(async () => {
      await result.current.exportDaw(dawBody, "tok")
    })

    await waitFor(() => expect(result.current.state.phase).toBe("error"))
  })
})
