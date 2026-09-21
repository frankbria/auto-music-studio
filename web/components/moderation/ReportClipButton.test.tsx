import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ReportClipButton } from "@/components/moderation/ReportClipButton"
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

describe("ReportClipButton", () => {
  it("is hidden when signed out, outside a provider, or on the viewer's own clip", () => {
    const { unmount } = withAuth(<ReportClipButton clipId="c1" />, {
      ...SIGNED_IN,
      isAuthenticated: false,
      accessToken: null,
    })
    expect(
      screen.queryByRole("button", { name: "Report" })
    ).not.toBeInTheDocument()
    unmount()

    render(<ReportClipButton clipId="c1" />)
    expect(
      screen.queryByRole("button", { name: "Report" })
    ).not.toBeInTheDocument()

    withAuth(<ReportClipButton clipId="c1" isOwner />)
    expect(
      screen.queryByRole("button", { name: "Report" })
    ).not.toBeInTheDocument()
  })

  it("opens a modal with the four categories (AC1)", async () => {
    withAuth(<ReportClipButton clipId="c1" />)
    await userEvent.click(screen.getByRole("button", { name: "Report" }))

    expect(
      screen.getByRole("dialog", { name: "Report clip" })
    ).toBeInTheDocument()
    for (const label of [
      "Inappropriate content",
      "Copyright concern",
      "Spam",
      "Other",
    ]) {
      expect(screen.getByRole("radio", { name: label })).toBeInTheDocument()
    }
    expect(screen.getByRole("button", { name: "Submit report" })).toBeDisabled()
  })

  it("submits category + details and shows the confirmation (AC2)", async () => {
    const fetchMock = stubFetch(201, {
      detail: "Report received. Our team will review it.",
    })
    withAuth(<ReportClipButton clipId="c1" />)
    await userEvent.click(screen.getByRole("button", { name: "Report" }))
    await userEvent.click(
      screen.getByRole("radio", { name: "Copyright concern" })
    )
    await userEvent.type(screen.getByLabelText(/details/i), "my song")
    await userEvent.click(screen.getByRole("button", { name: "Submit report" }))

    expect(
      await screen.findByText("Report received. Our team will review it.")
    ).toBeInTheDocument()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1/report")
    expect(opts.method).toBe("POST")
    expect(opts.headers.authorization).toBe("Bearer tok")
    expect(JSON.parse(opts.body)).toEqual({
      category: "copyright",
      details: "my song",
    })
  })

  it("shows the duplicate message on a 409 (AC4)", async () => {
    stubFetch(409, { detail: "You have already reported this clip." })
    withAuth(<ReportClipButton clipId="c1" />)
    await userEvent.click(screen.getByRole("button", { name: "Report" }))
    await userEvent.click(screen.getByRole("radio", { name: "Spam" }))
    await userEvent.click(screen.getByRole("button", { name: "Submit report" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You have already reported this clip."
    )
  })

  it("renders a custom trigger", async () => {
    withAuth(
      <ReportClipButton
        clipId="c1"
        trigger={(open) => <button onClick={open}>Flag it</button>}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: "Flag it" }))
    expect(
      screen.getByRole("dialog", { name: "Report clip" })
    ).toBeInTheDocument()
  })
})
