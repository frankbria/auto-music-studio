import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ClipAppealStatus } from "@/components/moderation/ClipAppealStatus"
import type { AppealView } from "@/lib/appeals"
import { SIGNED_IN, SignedIn, type AuthValue } from "@/test/signed-in"

function withAuth(ui: ReactNode, value: AuthValue | null = SIGNED_IN) {
  return render(<SignedIn value={value}>{ui}</SignedIn>)
}

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

function appeal(overrides: Partial<AppealView> = {}): AppealView {
  return {
    id: "a1",
    clip_id: "c1",
    action: "remove",
    reason: "not spam",
    context: null,
    status: "pending",
    admin_note: null,
    created_at: "2026-01-01T00:00:00Z",
    decided_at: null,
    ...overrides,
  }
}

describe("ClipAppealStatus", () => {
  it("renders nothing for a normal clip with no appeal history", () => {
    const { container } = withAuth(
      <ClipAppealStatus
        clip={{ id: "c1", removed_at: null, content_warning: false }}
        appeal={null}
      />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("shows a removed badge and an Appeal entry when there is no appeal yet", () => {
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={null}
      />
    )
    expect(screen.getByText("Removed by moderation")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Appeal" })).toBeInTheDocument()
  })

  it("shows a content warning badge for a flagged clip", () => {
    withAuth(
      <ClipAppealStatus
        clip={{ id: "c1", removed_at: null, content_warning: true }}
        appeal={null}
      />
    )
    expect(screen.getByText("Content warning")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Appeal" })).toBeInTheDocument()
  })

  it("submits an appeal and shows the confirmation (AC)", async () => {
    const fetchMock = stubFetch(201, appeal())
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={null}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: "Appeal" }))
    expect(
      screen.getByRole("dialog", { name: "Appeal moderation decision" })
    ).toBeInTheDocument()
    await userEvent.type(
      screen.getByLabelText(/reason for appeal/i),
      "This was a mistake"
    )
    await userEvent.click(screen.getByRole("button", { name: "Submit appeal" }))

    expect(
      await screen.findByText("Appeal submitted. Our team will review it.")
    ).toBeInTheDocument()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/appeal")
    expect(opts.method).toBe("POST")
    expect(JSON.parse(opts.body)).toEqual({
      reason: "This was a mistake",
      context: null,
    })
  })

  it("shows the duplicate-appeal detail on a 409", async () => {
    stubFetch(409, { detail: "You have already appealed this decision." })
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={null}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: "Appeal" }))
    await userEvent.type(screen.getByLabelText(/reason for appeal/i), "why")
    await userEvent.click(screen.getByRole("button", { name: "Submit appeal" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You have already appealed this decision."
    )
  })

  it("hides the Appeal entry and shows a pending notice for a pending appeal", () => {
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={appeal({ status: "pending" })}
      />
    )
    expect(screen.getByText("Appeal pending")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Appeal" })
    ).not.toBeInTheDocument()
  })

  it("shows the info-request form and PATCHes new context", async () => {
    const fetchMock = stubFetch(200, appeal({ status: "pending" }))
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={appeal({
          status: "info_requested",
          admin_note: "Need more detail",
        })}
      />
    )
    expect(screen.getByText("More information requested")).toBeInTheDocument()
    expect(screen.getByText("Need more detail")).toBeInTheDocument()
    await userEvent.type(
      screen.getByLabelText(/additional context/i),
      "Here is more detail"
    )
    await userEvent.click(screen.getByRole("button", { name: "Send" }))

    expect(
      await screen.findByText("Additional information sent.")
    ).toBeInTheDocument()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/appeal")
    expect(opts.method).toBe("PATCH")
    expect(JSON.parse(opts.body)).toEqual({ context: "Here is more detail" })
  })

  it("shows the denial notice and admin note for an upheld appeal, with no Appeal entry", () => {
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-01-01T00:00:00Z",
          content_warning: false,
        }}
        appeal={appeal({ status: "upheld", admin_note: "Confirmed spam" })}
      />
    )
    expect(screen.getByText("Appeal denied")).toBeInTheDocument()
    expect(screen.getByText("Confirmed spam")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Appeal" })
    ).not.toBeInTheDocument()
  })

  it("offers a new appeal when the clip is removed after a denied flag appeal", () => {
    withAuth(
      <ClipAppealStatus
        clip={{
          id: "c1",
          removed_at: "2026-02-01T00:00:00Z",
          content_warning: true,
        }}
        appeal={appeal({ action: "flag", status: "upheld" })}
      />
    )
    expect(screen.getByRole("button", { name: "Appeal" })).toBeInTheDocument()
  })

  it("shows an approved notice for a reversed appeal even once the clip is clear", () => {
    withAuth(
      <ClipAppealStatus
        clip={{ id: "c1", removed_at: null, content_warning: false }}
        appeal={appeal({ status: "reversed" })}
      />
    )
    expect(screen.getByText("Appeal approved")).toBeInTheDocument()
    expect(screen.queryByText("Removed by moderation")).not.toBeInTheDocument()
  })
})
