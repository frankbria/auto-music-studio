import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AppealsPanel } from "@/components/moderation/AppealsPanel"
import type { AppealQueueItem } from "@/lib/moderation"

function item(overrides: Partial<AppealQueueItem> = {}): AppealQueueItem {
  return {
    id: "ap1",
    clip_id: "c1",
    action: "remove",
    reason: "This was a false positive",
    context: "See attached lyrics",
    status: "pending",
    admin_note: null,
    created_at: "2026-09-01T00:00:00Z",
    decided_at: null,
    clip_title: "Song A",
    clip_deleted: false,
    creator_id: "u2",
    creator_name: "Creator Two",
    action_reason: "Flagged as spam",
    action_at: "2026-08-30T00:00:00Z",
    ...overrides,
  }
}

// Routes the BFF paths the panel calls.
function stubBackend(
  appeals: AppealQueueItem[],
  decisionResult?: AppealQueueItem
) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), { status })
    if (url.startsWith("/api/admin/moderation/appeals?"))
      return json(200, { appeals })
    if (
      url.startsWith("/api/admin/moderation/appeals/") &&
      init?.method === "POST"
    )
      return json(200, decisionResult ?? appeals[0])
    return json(404, { detail: "not found" })
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("AppealsPanel", () => {
  it("lists open appeals with clip/creator/action/reason/status/time", async () => {
    stubBackend([item()])
    render(<AppealsPanel accessToken="tok" />)

    expect(await screen.findByText("Song A")).toBeInTheDocument()
    expect(screen.getByText("Creator Two")).toBeInTheDocument()
    expect(screen.getByText("Removed")).toBeInTheDocument()
    expect(screen.getByText(/Flagged as spam/)).toBeInTheDocument()
    expect(screen.getByText("This was a false positive")).toBeInTheDocument()
    expect(screen.getByText(/See attached lyrics/)).toBeInTheDocument()
    expect(screen.getByText("Pending")).toBeInTheDocument()
  })

  it("shows 'Clip deleted' when the clip no longer exists", async () => {
    stubBackend([item({ clip_deleted: true, clip_title: null })])
    render(<AppealsPanel accessToken="tok" />)
    expect(await screen.findByText("Clip deleted")).toBeInTheDocument()
  })

  it("defaults to the open queue, and toggling to All refetches", async () => {
    const fetchMock = stubBackend([item()])
    render(<AppealsPanel accessToken="tok" />)
    await screen.findByText("Song A")
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/admin/moderation/appeals?status=open"
    )

    await userEvent.selectOptions(screen.getByLabelText("Show"), "All appeals")
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/admin/moderation/appeals?status=all",
        expect.anything()
      )
    )
  })

  it("hides decision buttons for an already-decided appeal", async () => {
    stubBackend([
      item({ status: "upheld", decided_at: "2026-09-02T00:00:00Z" }),
    ])
    render(<AppealsPanel accessToken="tok" />)
    await screen.findByText("Song A")
    expect(
      screen.queryByRole("button", { name: "Uphold" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Reverse" })
    ).not.toBeInTheDocument()
  })

  it("uphold posts the decision, shows a notice, and refetches", async () => {
    const decided = item({
      status: "upheld",
      decided_at: "2026-09-02T00:00:00Z",
    })
    const fetchMock = stubBackend([item()], decided)
    render(<AppealsPanel accessToken="tok" />)
    await userEvent.click(await screen.findByRole("button", { name: "Uphold" }))
    expect(
      screen.getByRole("dialog", { name: /Uphold appeal for Song A/ })
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Uphold" }))

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Upheld appeal for Song A."
      )
    )
    const postCall = fetchMock.mock.calls.find(
      (call) => call[1]?.method === "POST"
    )
    expect(postCall?.[0]).toBe("/api/admin/moderation/appeals/ap1")
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      decision: "uphold",
    })
  })

  it("reverse posts the decision with a note", async () => {
    const decided = item({
      status: "reversed",
      decided_at: "2026-09-02T00:00:00Z",
    })
    const fetchMock = stubBackend([item()], decided)
    render(<AppealsPanel accessToken="tok" />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Reverse" })
    )
    await userEvent.type(screen.getByLabelText(/note/i), "Mistake confirmed")
    await userEvent.click(screen.getByRole("button", { name: "Reverse" }))

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Reversed appeal for Song A."
      )
    )
    const postCall = fetchMock.mock.calls.find(
      (call) => call[1]?.method === "POST"
    )
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      decision: "reverse",
      note: "Mistake confirmed",
    })
  })

  it("requires a note before Request info can be submitted", async () => {
    stubBackend([item()], item({ status: "info_requested" }))
    render(<AppealsPanel accessToken="tok" />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Request info" })
    )
    const dialog = screen.getByRole("dialog")
    const submit = within(dialog).getByRole("button", { name: "Request info" })
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/note/i), "Need lyric proof")
    expect(submit).toBeEnabled()
  })

  it("shows an alert when the queue fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Admin access required." }), {
          status: 403,
        })
      )
    )
    render(<AppealsPanel accessToken="tok" />)
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Admin access required."
    )
  })
})
