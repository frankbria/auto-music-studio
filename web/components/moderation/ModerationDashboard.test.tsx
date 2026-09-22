import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ModerationDashboard } from "@/components/moderation/ModerationDashboard"
import type { ModerationLogEntry, QueueItem } from "@/lib/moderation"

function item(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    clip_id: "c1",
    clip_deleted: false,
    title: "Song A",
    style_tags: ["lofi"],
    creator_id: "u2",
    creator_name: "Creator Two",
    creator_banned: false,
    visibility: "public",
    content_warning: false,
    report_count: 3,
    categories: { spam: 2, copyright: 1 },
    moderation_flags: [],
    sources: ["report"],
    severity: 2,
    latest_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

const SONG_A = item()
const SONG_B = item({
  clip_id: "c2",
  title: "Song B",
  report_count: 1,
  categories: { inappropriate: 1 },
  sources: ["report", "automated"],
  moderation_flags: ["profanity"],
  severity: 3,
  latest_at: "2026-09-03T00:00:00Z",
})
const SONG_C = item({
  clip_id: "c3",
  title: "Song C",
  creator_id: "u3",
  creator_name: "Creator Three",
  creator_banned: true,
  content_warning: true,
  report_count: 0,
  categories: {},
  sources: ["automated"],
  moderation_flags: ["hate"],
  severity: 3,
  latest_at: "2026-09-02T00:00:00Z",
})
const DELETED = item({
  clip_id: "gone",
  clip_deleted: true,
  title: null,
  style_tags: [],
  creator_id: null,
  creator_name: null,
  visibility: null,
  report_count: 1,
  categories: { other: 1 },
  severity: 1,
})

type Backend = {
  queue: QueueItem[]
  log?: ModerationLogEntry[]
  results?: { ok: boolean; detail?: string }[]
  queueStatus?: number
}

// Routes the BFF paths the dashboard calls; each action answers ok for every id
// unless `results` overrides it.
function stubBackend(backend: Backend) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), { status })
    if (url === "/api/admin/moderation/queue")
      return json(
        backend.queueStatus ?? 200,
        backend.queueStatus
          ? { detail: "Admin access required." }
          : { items: backend.queue }
      )
    if (url.startsWith("/api/admin/moderation/log"))
      return json(200, { entries: backend.log ?? [] })
    const body = JSON.parse(String(init?.body))
    const key = url.endsWith("/clips") ? "clip_id" : "user_id"
    const ids: string[] = body.clip_ids ?? body.user_ids
    return json(200, {
      results: ids.map((id, i) => ({
        [key]: id,
        ...(backend.results?.[i] ?? { ok: true }),
      })),
    })
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function actionCalls(fetchMock: ReturnType<typeof stubBackend>) {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === "POST")
    .map(([url, init]) => ({ url, body: JSON.parse(String(init?.body)) }))
}

function queueCalls(fetchMock: ReturnType<typeof stubBackend>) {
  return fetchMock.mock.calls.filter(
    ([url]) => url === "/api/admin/moderation/queue"
  ).length
}

async function rowFor(title: string) {
  return (await screen.findByText(title)).closest("tr") as HTMLElement
}

function renderedTitles() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[1].textContent ?? "")
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("ModerationDashboard", () => {
  it("lists every queued clip with its reports, sources, creator and player (AC1)", async () => {
    stubBackend({ queue: [SONG_A, SONG_B, SONG_C] })
    render(<ModerationDashboard accessToken="tok" />)

    const a = await rowFor("Song A")
    expect(within(a).getByText("Creator Two")).toBeInTheDocument()
    expect(within(a).getByText("3")).toBeInTheDocument()
    expect(within(a).getByText("Spam (2)")).toBeInTheDocument()
    expect(within(a).getByText("Copyright concern (1)")).toBeInTheDocument()
    expect(within(a).getByText("User report")).toBeInTheDocument()
    expect(within(a).getByText("lofi")).toBeInTheDocument()
    expect(a.querySelector("audio")).toHaveAttribute(
      "src",
      "/api/clips/c1/stream"
    )

    const b = await rowFor("Song B")
    expect(within(b).getByText("Automated")).toBeInTheDocument()
    expect(within(b).getByText("profanity")).toBeInTheDocument()

    const c = await rowFor("Song C")
    expect(within(c).getByText("Banned")).toBeInTheDocument()
    expect(within(c).getByText("Content warning")).toBeInTheDocument()
    expect(
      within(c).queryByRole("button", { name: "Ban creator" })
    ).not.toBeInTheDocument()
  })

  it("offers only Approve on a report whose clip was deleted", async () => {
    stubBackend({ queue: [DELETED] })
    render(<ModerationDashboard accessToken="tok" />)

    const row = await rowFor("Clip deleted")
    expect(
      within(row).getByRole("button", { name: "Approve" })
    ).toBeInTheDocument()
    for (const name of ["Remove", "Flag", "Warn creator", "Ban creator"])
      expect(
        within(row).queryByRole("button", { name })
      ).not.toBeInTheDocument()
    expect(row.querySelector("audio")).toBeNull()
  })

  it("shows an empty state when nothing is waiting", async () => {
    stubBackend({ queue: [] })
    render(<ModerationDashboard accessToken="tok" />)
    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument()
  })

  it("shows the load failure instead of an empty queue", async () => {
    stubBackend({ queue: [], queueStatus: 403 })
    render(<ModerationDashboard accessToken="tok" />)
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Admin access required."
    )
    expect(screen.queryByText("Nothing to review.")).not.toBeInTheDocument()
  })

  it("approves a clip in one click, then refetches the queue (AC2)", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")
    expect(queueCalls(fetchMock)).toBe(1)

    await userEvent.click(within(row).getByRole("button", { name: "Approve" }))

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Approved 1 clip."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/clips",
        body: { action: "approve", clip_ids: ["c1"] },
      },
    ])
    await waitFor(() => expect(queueCalls(fetchMock)).toBe(2))
  })

  it("asks for confirmation before removing, and sends the reason (AC3)", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")

    await userEvent.click(within(row).getByRole("button", { name: "Remove" }))
    const dialog = screen.getByRole("dialog", { name: "Remove 1 clip?" })
    expect(actionCalls(fetchMock)).toEqual([])

    await userEvent.type(
      within(dialog).getByLabelText("Reason (optional)"),
      "stolen beat"
    )
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Remove" })
    )

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Removed 1 clip."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/clips",
        body: { action: "remove", clip_ids: ["c1"], reason: "stolen beat" },
      },
    ])
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("sends nothing when a destructive action is cancelled", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")

    await userEvent.click(
      within(row).getByRole("button", { name: "Ban creator" })
    )
    const dialog = screen.getByRole("dialog", { name: "Ban 1 creator?" })
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" })
    )

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(actionCalls(fetchMock)).toEqual([])
  })

  it("bans a creator after confirmation (AC4)", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")

    await userEvent.click(
      within(row).getByRole("button", { name: "Ban creator" })
    )
    const dialog = screen.getByRole("dialog", { name: "Ban 1 creator?" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Ban" }))

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Banned 1 creator."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/users",
        body: { action: "ban", user_ids: ["u2"] },
      },
    ])
  })

  it("flags in one click, without a confirmation step", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")

    await userEvent.click(within(row).getByRole("button", { name: "Flag" }))
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Flagged 1 clip."
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/clips",
        body: { action: "flag", clip_ids: ["c1"] },
      },
    ])
  })

  it("asks for a reason before warning a creator, and sends it", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song A")

    await userEvent.click(
      within(row).getByRole("button", { name: "Warn creator" })
    )
    const dialog = screen.getByRole("dialog", { name: "Warn 1 creator?" })
    expect(actionCalls(fetchMock)).toEqual([])

    await userEvent.type(
      within(dialog).getByLabelText("Reason (optional)"),
      "misleading tags"
    )
    await userEvent.click(within(dialog).getByRole("button", { name: "Warn" }))

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Warned 1 creator."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/users",
        body: { action: "warn", user_ids: ["u2"], reason: "misleading tags" },
      },
    ])
  })

  it("applies bulk actions to the selection, deduping creators", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A, SONG_B, SONG_C] })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")
    expect(
      screen.queryByRole("toolbar", { name: "Bulk actions" })
    ).not.toBeInTheDocument()

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Song A" })
    )
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Song B" })
    )
    const bar = screen.getByRole("toolbar", { name: "Bulk actions" })
    expect(bar).toHaveTextContent("2 selected")

    await userEvent.click(
      within(bar).getByRole("button", { name: "Warn creators" })
    )
    // The reason stays optional: confirming with it blank still warns.
    const dialog = screen.getByRole("dialog", { name: "Warn 1 creator?" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Warn" }))
    await screen.findByRole("status")
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/users",
        body: { action: "warn", user_ids: ["u2"] },
      },
    ])
    // The selection clears once an action has run.
    expect(
      screen.queryByRole("toolbar", { name: "Bulk actions" })
    ).not.toBeInTheDocument()
  })

  it("selects every visible row and bulk-removes them after confirmation", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A, SONG_B, DELETED] })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.click(screen.getByRole("checkbox", { name: "Select all" }))
    const bar = screen.getByRole("toolbar", { name: "Bulk actions" })
    expect(bar).toHaveTextContent("3 selected")

    await userEvent.click(within(bar).getByRole("button", { name: "Remove" }))
    const dialog = screen.getByRole("dialog", { name: "Remove 2 clips?" })
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Remove" })
    )

    await screen.findByRole("status")
    // A deleted clip has nothing left to remove; only live clips are sent.
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/clips",
        body: { action: "remove", clip_ids: ["c1", "c2"] },
      },
    ])
  })

  it("reports per-target failures inline", async () => {
    stubBackend({
      queue: [SONG_A, SONG_B],
      results: [{ ok: true }, { ok: false, detail: "Clip not found." }],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")
    await userEvent.click(screen.getByRole("checkbox", { name: "Select all" }))
    await userEvent.click(
      within(screen.getByRole("toolbar", { name: "Bulk actions" })).getByRole(
        "button",
        { name: "Flag" }
      )
    )

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Flagged 1 clip."
    )
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Song B: Clip not found."
    )
  })

  it("sorts by severity or recency and filters by source and category", async () => {
    stubBackend({ queue: [SONG_A, SONG_B, SONG_C] })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")
    expect(renderedTitles()).toEqual([
      expect.stringContaining("Song A"),
      expect.stringContaining("Song B"),
      expect.stringContaining("Song C"),
    ])

    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "newest")
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual([
      "Song B",
      "Song C",
      "Song A",
    ])

    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "severity")
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual([
      "Song B",
      "Song C",
      "Song A",
    ])

    await userEvent.selectOptions(screen.getByLabelText("Source"), "automated")
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual([
      "Song B",
      "Song C",
    ])

    await userEvent.selectOptions(screen.getByLabelText("Source"), "all")
    await userEvent.selectOptions(
      screen.getByLabelText("Category"),
      "copyright"
    )
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual(["Song A"])
  })

  it("shows the activity log with each action's target and reason (AC5)", async () => {
    const fetchMock = stubBackend({
      queue: [],
      log: [
        {
          id: "l1",
          actor_id: "admin-1",
          action: "ban",
          target_type: "user",
          target_id: "u2",
          reason: "repeat spam",
          details: {},
          created_at: "2026-09-20T12:00:00Z",
        },
      ],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))

    const row = (await screen.findByText("Banned user")).closest(
      "tr"
    ) as HTMLElement
    expect(row).toHaveTextContent("user u2")
    expect(row).toHaveTextContent("admin-1")
    expect(row).toHaveTextContent("repeat spam")
    expect(
      fetchMock.mock.calls.some(
        ([url]) => url === "/api/admin/moderation/log?limit=100"
      )
    ).toBe(true)
  })
})
