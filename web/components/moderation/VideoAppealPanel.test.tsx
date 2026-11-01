import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { VideoAppealPanel } from "@/components/moderation/VideoAppealPanel"
import type { AppealView } from "@/lib/appeals"
import { SignedIn } from "@/test/signed-in"

const pendingVideoAppeal: AppealView = {
  id: "va",
  clip_id: "c1",
  video_id: "v1",
  action: "unpublish",
  reason: "my footage",
  context: null,
  status: "pending",
  admin_note: null,
  created_at: "2026-01-01T00:00:00Z",
  decided_at: null,
}

function stubBackend(myAppeals: AppealView[]) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/users/me/appeals"))
      return new Response(
        JSON.stringify({ appeals: myAppeals, next_cursor: null }),
        { status: 200 }
      )
    return new Response(
      JSON.stringify({ ...pendingVideoAppeal, reason: String(init?.body) }),
      { status: 201 }
    )
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("VideoAppealPanel (#623)", () => {
  it("appeals the takedown through the video's appeal", async () => {
    const fetchMock = stubBackend([])
    render(
      <SignedIn>
        <VideoAppealPanel videoId="v1" />
      </SignedIn>
    )

    expect(
      screen.getByText(/Moderation took this video down/)
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Appeal" }))
    await userEvent.type(
      screen.getByLabelText("Reason for appeal"),
      "I shot it"
    )
    await userEvent.click(screen.getByRole("button", { name: /submit/i }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/videos/v1/appeal" && init?.method === "POST"
        )
      ).toBe(true)
    )
  })

  it("shows a pending appeal instead of offering another", async () => {
    stubBackend([pendingVideoAppeal])
    render(
      <SignedIn>
        <VideoAppealPanel videoId="v1" />
      </SignedIn>
    )

    expect(await screen.findByText("Appeal pending")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Appeal" })
    ).not.toBeInTheDocument()
  })
})
