import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { NotificationsView } from "@/components/notifications/NotificationsView"
import { NotificationsProvider } from "@/contexts/notifications-context"
import {
  notificationEvent,
  readCalls,
  stubNotificationsApi,
} from "@/test/notifications-api"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const removed = notificationEvent("r1", {
  clip_id: "c1",
  payload: { clip_id: "c1", title: "Takedown", reason: "Copyrighted sample" },
})
const warning = notificationEvent("w1", {
  event_type: "moderation_warning",
  clip_id: null,
  payload: { reason: "Mislabelled uploads" },
})
const live = notificationEvent("d1", {
  event_type: "status_live",
  channel: "soundcloud",
  clip_id: null,
  payload: { title: "Neon" },
  read: true,
})

function renderView() {
  return render(
    <SignedIn>
      <NotificationsProvider>
        <NotificationsView />
      </NotificationsProvider>
    </SignedIn>
  )
}

describe("NotificationsView (US-20.6, #537)", () => {
  it("shows a removed-clip notice and a warning with their reasons, linked to the content", async () => {
    stubNotificationsApi([[removed, warning, live]])
    renderView()

    const removal = await screen.findByText(
      'Moderation removed "Takedown". Reason: Copyrighted sample'
    )
    expect(removal.closest("a")).toHaveAttribute("href", "/song/c1")
    expect(
      screen.getByText(
        "You received a moderation warning. Reason: Mislabelled uploads"
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText('"Neon" is now live on soundcloud.')
    ).toBeInTheDocument()
    expect(screen.getByText("2 unread")).toBeInTheDocument()
  })

  it("shows an unread indicator on unread notifications only (AC3)", async () => {
    stubNotificationsApi([[removed, warning, live]])
    renderView()
    await screen.findAllByTestId("notification-item")
    expect(screen.getAllByTestId("unread-dot")).toHaveLength(2)
  })

  it("marks a single notification read on click, clearing its dot and saving it (AC3)", async () => {
    const user = userEvent.setup()
    const fetchMock = stubNotificationsApi([[removed, warning]])
    renderView()

    await user.click(await screen.findByText(/Moderation removed "Takedown"/))

    expect(screen.getAllByTestId("unread-dot")).toHaveLength(1)
    expect(readCalls(fetchMock)).toEqual([{ ids: ["r1"] }])
  })

  it('"Mark all as read" clears every unread indicator and disables itself (AC4)', async () => {
    const user = userEvent.setup()
    const fetchMock = stubNotificationsApi([[removed, warning]])
    renderView()
    const button = screen.getByRole("button", { name: "Mark all as read" })
    await waitFor(() => expect(button).toBeEnabled())

    await user.click(button)

    expect(screen.queryAllByTestId("unread-dot")).toHaveLength(0)
    expect(button).toBeDisabled()
    expect(screen.getByText("You're all caught up")).toBeInTheDocument()
    expect(readCalls(fetchMock)).toEqual([{}])
  })

  it("pages older notifications from the API", async () => {
    const user = userEvent.setup()
    stubNotificationsApi([[removed], [warning]])
    renderView()

    await user.click(
      await screen.findByRole("button", { name: "Show older notifications" })
    )

    await waitFor(() =>
      expect(screen.getAllByTestId("notification-item")).toHaveLength(2)
    )
    expect(
      screen.queryByRole("button", { name: "Show older notifications" })
    ).not.toBeInTheDocument()
  })

  it("shows the empty state when there are no notices", async () => {
    stubNotificationsApi([[]])
    renderView()
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument()
  })
})
