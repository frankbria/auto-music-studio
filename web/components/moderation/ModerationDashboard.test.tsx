import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ModerationDashboard } from "@/components/moderation/ModerationDashboard"
import type { ModerationLogEntry, QueueItem } from "@/lib/moderation"

function item(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    target_type: "clip",
    target_id: overrides.clip_id ?? "c1",
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
const VIDEO = item({
  target_type: "video",
  target_id: "v1",
  clip_id: "c9",
  title: "Song V",
  description: "war footage",
  published: true,
  visibility: null,
  report_count: 0,
  categories: {},
  sources: ["automated"],
  moderation_flags: ["violent extremism"],
  severity: 3,
})
const ARTWORK = item({
  target_type: "artwork",
  target_id: "a1",
  clip_id: "c8",
  title: "Song Art",
  description: "burning city",
  visibility: null,
  report_count: 0,
  categories: {},
  sources: ["automated"],
  moderation_flags: ["violent extremism"],
  severity: 3,
})
const VOICE = item({
  target_type: "voice_model",
  target_id: "m1",
  clip_id: null,
  title: "Dark Tenor",
  description: "grim themes",
  style_tags: [],
  visibility: null,
  report_count: 0,
  categories: {},
  sources: ["automated"],
  moderation_flags: ["sexual violence"],
  severity: 3,
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
  /** The queue's rows, or a function of the request's sort/filter/cursor params. */
  queue:
    | QueueItem[]
    | ((params: URLSearchParams) => QueueItem[] | Promise<QueueItem[]>)
  /** Answered as next_cursor when the request carries no cursor (#540). */
  queueNext?: string
  log?: ModerationLogEntry[]
  /** The log page served for a request carrying this cursor. */
  logPages?: Record<string, ModerationLogEntry[]>
  logNext?: string
  results?: { ok: boolean; detail?: string }[]
  queueStatus?: number
}

// Routes the BFF paths the dashboard calls; each action answers ok for every id
// unless `results` overrides it.
function stubBackend(backend: Backend) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), { status })
    const params = new URL(url, "http://bff").searchParams
    const cursor = params.get("cursor")
    if (url.startsWith("/api/admin/moderation/queue"))
      return json(
        backend.queueStatus ?? 200,
        backend.queueStatus
          ? { detail: "Admin access required." }
          : {
              items:
                typeof backend.queue === "function"
                  ? await backend.queue(params)
                  : backend.queue,
              next_cursor: cursor ? null : (backend.queueNext ?? null),
            }
      )
    if (url.startsWith("/api/admin/moderation/log"))
      return json(200, {
        entries: cursor
          ? (backend.logPages?.[cursor] ?? [])
          : (backend.log ?? []),
        next_cursor: cursor ? null : (backend.logNext ?? null),
      })
    if (url.startsWith("/api/admin/moderation/appeals"))
      return json(200, { appeals: [] })
    const body = JSON.parse(String(init?.body))
    const key = url.endsWith("/clips")
      ? "clip_id"
      : url.endsWith("/users")
        ? "user_id"
        : "id"
    const ids: string[] = body.clip_ids ?? body.user_ids ?? body.ids
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

function queueUrls(fetchMock: ReturnType<typeof stubBackend>) {
  return fetchMock.mock.calls
    .map(([url]) => url)
    .filter((url) => url.startsWith("/api/admin/moderation/queue"))
}

function queueCalls(fetchMock: ReturnType<typeof stubBackend>) {
  return queueUrls(fetchMock).length
}

function logEntry(
  overrides: Partial<ModerationLogEntry> = {}
): ModerationLogEntry {
  return {
    id: "l1",
    actor_id: "admin-1",
    actor_name: null,
    action: "ban",
    target_type: "user",
    target_id: "u2",
    target_label: null,
    reason: null,
    details: {},
    created_at: "2026-09-20T12:00:00Z",
    ...overrides,
  }
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

  it("shows each item's type, and a flagged video's prompt and player (#539)", async () => {
    stubBackend({ queue: [SONG_A, VIDEO, ARTWORK, VOICE] })
    render(<ModerationDashboard accessToken="tok" />)

    expect(within(await rowFor("Song A")).getByText("Clip")).toBeInTheDocument()

    const video = await rowFor("Song V")
    expect(within(video).getByText("Video")).toBeInTheDocument()
    expect(within(video).getByText("war footage")).toBeInTheDocument()
    expect(within(video).getByText("violent extremism")).toBeInTheDocument()
    expect(video.querySelector("video")).toHaveAttribute(
      "src",
      "/api/videos/v1/stream"
    )
    expect(video.querySelector("audio")).toBeNull()

    const art = await rowFor("Song Art")
    expect(within(art).getByText("Artwork")).toBeInTheDocument()
    expect(within(art).getByText("burning city")).toBeInTheDocument()

    const voice = await rowFor("Dark Tenor")
    expect(within(voice).getByText("Voice model")).toBeInTheDocument()
    expect(within(voice).getByText("grim themes")).toBeInTheDocument()
  })

  it("offers each type only the actions that fit it (#539)", async () => {
    stubBackend({ queue: [VIDEO, ARTWORK, VOICE] })
    render(<ModerationDashboard accessToken="tok" />)
    const names = (row: HTMLElement) =>
      within(row)
        .getAllByRole("button")
        .map((b) => b.textContent)

    expect(names(await rowFor("Song V"))).toEqual([
      "Approve",
      "Unpublish",
      "Warn creator",
      "Ban creator",
    ])
    expect(names(await rowFor("Song Art"))).toEqual([
      "Approve",
      "Drop",
      "Warn creator",
      "Ban creator",
    ])
    expect(names(await rowFor("Dark Tenor"))).toEqual([
      "Approve",
      "Warn creator",
      "Ban creator",
    ])
  })

  it("unpublishes a video after confirmation, with the reason (#539)", async () => {
    const fetchMock = stubBackend({ queue: [VIDEO] })
    render(<ModerationDashboard accessToken="tok" />)
    const row = await rowFor("Song V")

    await userEvent.click(
      within(row).getByRole("button", { name: "Unpublish" })
    )
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Unpublish 1 video?")
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "gore")
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Unpublish" })
    )

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Unpublished 1 video."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/content",
        body: {
          target_type: "video",
          action: "unpublish",
          ids: ["v1"],
          reason: "gore",
        },
      },
    ])
  })

  it("drops artwork after confirmation (#539)", async () => {
    const fetchMock = stubBackend({ queue: [ARTWORK] })
    render(<ModerationDashboard accessToken="tok" />)

    await userEvent.click(
      within(await rowFor("Song Art")).getByRole("button", { name: "Drop" })
    )
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: "Drop" }))

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Dropped 1 artwork image."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/content",
        body: { target_type: "artwork", action: "drop", ids: ["a1"] },
      },
    ])
  })

  it("bulk-approves a mixed selection across endpoints (#539)", async () => {
    const fetchMock = stubBackend({ queue: [SONG_A, VIDEO, VOICE] })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.click(screen.getByRole("checkbox", { name: "Select all" }))
    const toolbar = screen.getByRole("toolbar", { name: "Bulk actions" })
    expect(
      within(toolbar).getByRole("button", { name: "Unpublish videos" })
    ).toBeInTheDocument()
    expect(
      within(toolbar).queryByRole("button", { name: "Drop artwork" })
    ).not.toBeInTheDocument()
    await userEvent.click(
      within(toolbar).getByRole("button", { name: "Approve" })
    )

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Approved 3 items."
    )
    expect(actionCalls(fetchMock)).toEqual([
      {
        url: "/api/admin/moderation/clips",
        body: { action: "approve", clip_ids: ["c1"] },
      },
      {
        url: "/api/admin/moderation/content",
        body: { target_type: "video", action: "approve", ids: ["v1"] },
      },
      {
        url: "/api/admin/moderation/content",
        body: { target_type: "voice_model", action: "approve", ids: ["m1"] },
      },
    ])
  })

  it("labels a content action in the activity log by its type (#539)", async () => {
    stubBackend({
      queue: [],
      log: [
        logEntry({
          action: "unpublish",
          target_type: "video",
          target_id: "v1",
        }),
      ],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))

    expect(await screen.findByText("Unpublished video")).toBeInTheDocument()
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

  it("warns when a removal succeeded but its SoundCloud track stayed shared (#538)", async () => {
    stubBackend({
      queue: [SONG_A, SONG_B],
      results: [
        {
          ok: true,
          detail:
            "Couldn't make SoundCloud track sc-1 private; it may still be public on the owner's account.",
        },
        { ok: true },
      ],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")
    await userEvent.click(screen.getByRole("checkbox", { name: "Select all" }))
    await userEvent.click(
      within(screen.getByRole("toolbar", { name: "Bulk actions" })).getByRole(
        "button",
        { name: "Remove" }
      )
    )
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Remove 2 clips?" })).getByRole(
        "button",
        { name: "Remove" }
      )
    )

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Removed 2 clips."
    )
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Song A: Couldn't make SoundCloud track sc-1 private"
    )
    expect(screen.getByRole("alert")).not.toHaveTextContent("Song B")
  })

  it("asks the server for the chosen sort and filters, and shows its answer (#540)", async () => {
    const fetchMock = stubBackend({
      queue: (params) =>
        params.get("source") === "automated" ? [SONG_C] : [SONG_A, SONG_B],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "newest")
    await userEvent.selectOptions(screen.getByLabelText("Source"), "automated")
    await rowFor("Song C")
    expect(screen.queryByText("Song A")).not.toBeInTheDocument()

    await userEvent.selectOptions(
      screen.getByLabelText("Category"),
      "copyright"
    )
    await waitFor(() =>
      expect(queueUrls(fetchMock).at(-1)).toBe(
        "/api/admin/moderation/queue?sort=newest&source=automated&category=copyright"
      )
    )
  })

  it("says nothing matches when a filtered queue comes back empty", async () => {
    stubBackend({
      queue: (params) => (params.get("category") === "all" ? [SONG_A] : []),
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.selectOptions(screen.getByLabelText("Category"), "spam")

    expect(
      await screen.findByText("Nothing matches these filters.")
    ).toBeInTheDocument()
  })

  it("appends the next queue page on Load more, then hides the button (#540)", async () => {
    const fetchMock = stubBackend({
      queue: (params) => (params.get("cursor") === "q2" ? [SONG_C] : [SONG_A]),
      queueNext: "q2",
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.click(screen.getByRole("button", { name: "Load more" }))

    await rowFor("Song C")
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual([
      "Song A",
      "Song C",
    ])
    expect(queueUrls(fetchMock).at(-1)).toContain("cursor=q2")
    expect(
      screen.queryByRole("button", { name: "Load more" })
    ).not.toBeInTheDocument()
  })

  it("hides the previous rows while a new filter loads (#540)", async () => {
    stubBackend({
      queue: (params) =>
        params.get("source") === "automated"
          ? new Promise<QueueItem[]>(() => {})
          : [SONG_A],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await userEvent.click(within(await rowFor("Song A")).getByRole("checkbox"))

    await userEvent.selectOptions(screen.getByLabelText("Source"), "automated")

    expect(await screen.findByText("Loading queue...")).toBeInTheDocument()
    expect(screen.queryByText("Song A")).not.toBeInTheDocument()
    expect(
      screen.queryByRole("toolbar", { name: "Bulk actions" })
    ).not.toBeInTheDocument()
  })

  it("drops a Load more page that lands after the filters changed (#540)", async () => {
    let releaseLate: (items: QueueItem[]) => void = () => {}
    stubBackend({
      queue: (params) => {
        if (params.get("cursor") === "q2")
          return new Promise((resolve) => {
            releaseLate = resolve
          })
        return params.get("source") === "automated" ? [SONG_C] : [SONG_A]
      },
      queueNext: "q2",
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")

    await userEvent.click(screen.getByRole("button", { name: "Load more" }))
    await userEvent.selectOptions(screen.getByLabelText("Source"), "automated")
    await rowFor("Song C")
    releaseLate([SONG_B])

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText("Song B")).not.toBeInTheDocument()
    expect(renderedTitles().map((t) => t.slice(0, 6))).toEqual(["Song C"])
  })

  it("keeps Load more and the filters disabled until the post-action reload lands (#540)", async () => {
    let reloadArmed = false
    let reloadRequested = false
    let releaseReload: (items: QueueItem[]) => void = () => {}
    stubBackend({
      queue: (params) => {
        if (params.get("cursor")) return [SONG_C]
        if (!reloadArmed) return [SONG_A, SONG_B]
        reloadRequested = true
        return new Promise((resolve) => {
          releaseReload = resolve
        })
      },
      queueNext: "q2",
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song B")

    reloadArmed = true
    await userEvent.click(
      within(await rowFor("Song A")).getByRole("button", { name: "Approve" })
    )

    await waitFor(() => expect(reloadRequested).toBe(true))
    expect(screen.getByRole("button", { name: "Load more" })).toBeDisabled()
    // A filter change here would be superseded by the reload's click-time query.
    for (const label of ["Sort by", "Source", "Category"])
      expect(screen.getByLabelText(label)).toBeDisabled()

    releaseReload([SONG_B])
    await waitFor(() =>
      expect(screen.queryByText("Song A")).not.toBeInTheDocument()
    )
    expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled()
    expect(screen.getByLabelText("Sort by")).toBeEnabled()
  })

  it("reloads with the current token when it rotates mid-action (#540)", async () => {
    const backend = stubBackend({ queue: [SONG_A, SONG_B] })
    let releasePost: () => void = () => {}
    const posted = new Promise<void>((resolve) => {
      releasePost = resolve
    })
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") await posted
      return backend(url, init)
    })
    const { rerender } = render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song B")

    await userEvent.click(
      within(await rowFor("Song A")).getByRole("button", { name: "Approve" })
    )
    rerender(<ModerationDashboard accessToken="tok2" />)
    releasePost()

    await waitFor(async () =>
      expect(
        within(await rowFor("Song A")).getByRole("button", { name: "Approve" })
      ).toBeEnabled()
    )
    expect(screen.queryByText("Loading queue...")).not.toBeInTheDocument()
    const lastQueueGet = backend.mock.calls
      .filter(([url]) => url.startsWith("/api/admin/moderation/queue"))
      .at(-1)
    expect(
      (lastQueueGet?.[1]?.headers as Record<string, string>).authorization
    ).toBe("Bearer tok2")
  })

  it("goes back to the first page after an action (#540)", async () => {
    const fetchMock = stubBackend({
      queue: (params) => (params.get("cursor") === "q2" ? [SONG_C] : [SONG_A]),
      queueNext: "q2",
    })
    render(<ModerationDashboard accessToken="tok" />)
    await rowFor("Song A")
    await userEvent.click(screen.getByRole("button", { name: "Load more" }))
    await rowFor("Song C")

    await userEvent.click(
      within(await rowFor("Song A")).getByRole("button", { name: "Approve" })
    )

    await waitFor(() =>
      expect(queueUrls(fetchMock).at(-1)).not.toContain("cursor")
    )
    await waitFor(() =>
      expect(screen.queryByText("Song C")).not.toBeInTheDocument()
    )
  })

  it("names the admin and the target in the activity log (AC5, #540)", async () => {
    const fetchMock = stubBackend({
      queue: [],
      log: [
        logEntry({
          actor_name: "Ada Admin",
          target_label: "Creator Two",
          reason: "repeat spam",
        }),
      ],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))

    const row = (await screen.findByText("Banned user")).closest(
      "tr"
    ) as HTMLElement
    expect(row).toHaveTextContent("Creator Two")
    expect(row).toHaveTextContent("Ada Admin")
    expect(row).not.toHaveTextContent("admin-1")
    expect(row).toHaveTextContent("repeat spam")
    expect(
      fetchMock.mock.calls.some(
        ([url]) => url === "/api/admin/moderation/log?limit=100"
      )
    ).toBe(true)
  })

  it("falls back to raw ids when a log entry's admin or target is gone", async () => {
    stubBackend({ queue: [], log: [logEntry()] })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))

    const row = (await screen.findByText("Banned user")).closest(
      "tr"
    ) as HTMLElement
    expect(row).toHaveTextContent("user u2")
    expect(row).toHaveTextContent("admin-1")
  })

  it("labels a platform-written log entry with no actor as system (#538)", async () => {
    stubBackend({
      queue: [],
      log: [
        logEntry({
          id: "l2",
          actor_id: null,
          action: "soundcloud_unshare_failed",
          target_type: "clip",
          target_id: "c9",
        }),
      ],
    })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))

    const row = (await screen.findByText("SoundCloud un-share failed")).closest(
      "tr"
    ) as HTMLElement
    expect(row).toHaveTextContent("clip c9")
    expect(row).toHaveTextContent("system")
  })

  it("appends older log entries on Load more (#540)", async () => {
    const fetchMock = stubBackend({
      queue: [],
      log: [logEntry({ id: "l1", reason: "first page" })],
      logNext: "g2",
      logPages: { g2: [logEntry({ id: "l0", reason: "second page" })] },
    })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")
    await userEvent.click(screen.getByRole("tab", { name: "Activity log" }))
    await screen.findByText("first page")

    await userEvent.click(screen.getByRole("button", { name: "Load more" }))

    expect(await screen.findByText("second page")).toBeInTheDocument()
    expect(screen.getByText("first page")).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(
        ([url]) => url === "/api/admin/moderation/log?limit=100&cursor=g2"
      )
    ).toBe(true)
  })

  it("has an Appeals tab that loads the appeals queue (US-27.4)", async () => {
    const fetchMock = stubBackend({ queue: [] })
    render(<ModerationDashboard accessToken="tok" />)
    await screen.findByText("Nothing to review.")

    await userEvent.click(screen.getByRole("tab", { name: "Appeals" }))

    await screen.findByText("No appeals to review.")
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).startsWith("/api/admin/moderation/appeals?status=open")
      )
    ).toBe(true)
  })
})
