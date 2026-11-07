import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MasteringHistory } from "@/components/mastering/mastering-history"
import type { UseMasteringHistory } from "@/hooks/use-mastering-history"
import type { MasteringHistoryItem } from "@/lib/mastering"

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string
    children: React.ReactNode
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

const reload = vi.fn()
let history: UseMasteringHistory
const useMasteringHistory = vi.fn()
vi.mock("@/hooks/use-mastering-history", () => ({
  useMasteringHistory: (...a: unknown[]) => {
    useMasteringHistory(...a)
    return history
  },
}))

function job(over: Partial<MasteringHistoryItem>): MasteringHistoryItem {
  return {
    job_id: "j",
    status: "completed",
    profile: "streaming",
    service: "bakuage",
    is_approved: false,
    created_at: new Date().toISOString(),
    ...over,
  }
}

function ready(jobs: MasteringHistoryItem[]): UseMasteringHistory {
  return { state: { status: "ready", jobs }, reload }
}

afterEach(() => vi.clearAllMocks())

describe("MasteringHistory", () => {
  it("renders nothing until a song is selected", () => {
    history = ready([job({})])
    const { container } = render(<MasteringHistory clipId={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("loads the selected song's history with the refresh key", () => {
    history = { state: { status: "loading" }, reload }
    render(<MasteringHistory clipId="c1" refreshKey="completed" />)
    expect(useMasteringHistory).toHaveBeenCalledWith("c1", "completed")
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i)
  })

  it("renders an empty state when the song has no jobs", () => {
    history = ready([])
    render(<MasteringHistory clipId="c1" />)
    expect(
      screen.getByText(/no mastering jobs for this song yet/i)
    ).toBeInTheDocument()
  })

  it("shows an error with a retry", async () => {
    history = { state: { status: "error" }, reload }
    render(<MasteringHistory clipId="c1" />)
    expect(
      screen.getByText(/couldn.t load mastering history/i)
    ).toBeInTheDocument()
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /try again/i }))
    expect(reload).toHaveBeenCalled()
  })

  it("links an approved master to its song page", () => {
    history = ready([
      job({
        job_id: "a",
        is_approved: true,
        mastered_clip_id: "m1",
        profile: "club",
      }),
    ])
    render(<MasteringHistory clipId="c1" />)
    const link = screen.getByRole("link", { name: /club \/ dj/i })
    expect(link).toHaveAttribute("href", "/song/m1")
    expect(screen.getByText("Approved")).toBeInTheDocument()
  })

  it("shows non-approved jobs without a link and with their status", () => {
    history = ready([
      job({ job_id: "p", status: "processing" }),
      job({ job_id: "f", status: "failed", service: "landr" }),
    ])
    render(<MasteringHistory clipId="c1" />)
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByText(/processing/i)).toBeInTheDocument()
    expect(screen.getByText(/LANDR/)).toBeInTheDocument()
    expect(screen.getByText(/failed/i)).toBeInTheDocument()
  })
})
