import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { NewReleasesSection } from "@/components/explore/NewReleasesSection"
import { makeClip } from "@/test/clip-factory"
import { stubViewerAwareDiscover } from "@/test/discover-api"
import { SignedIn } from "@/test/signed-in"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("NewReleasesSection viewer ownership (#653)", () => {
  it("sends the viewer's token and offers Report only on someone else's clip", async () => {
    const fetchMock = stubViewerAwareDiscover(
      [
        makeClip({ id: "mine", title: "Mine" }),
        makeClip({ id: "theirs", title: "Theirs" }),
      ],
      "mine"
    )
    render(
      <SignedIn>
        <NewReleasesSection />
      </SignedIn>
    )

    await screen.findByText("Theirs")
    expect(screen.getAllByRole("button", { name: /report/i })).toHaveLength(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer tok")
  })

  it("stays anonymous for a signed-out visitor", async () => {
    const fetchMock = stubViewerAwareDiscover(
      [makeClip({ id: "theirs", title: "Theirs" })],
      "mine"
    )
    render(<NewReleasesSection />)

    await screen.findByText("Theirs")
    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).get("authorization")).toBeNull()
  })
})
