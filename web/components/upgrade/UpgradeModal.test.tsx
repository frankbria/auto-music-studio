import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { UpgradeModal } from "@/components/upgrade/UpgradeModal"
import { lockedFeature } from "@/lib/tiers"

describe("UpgradeModal (US-26.2 AC2)", () => {
  it("leads with the feature that was actually reached for", () => {
    // "Upgrade to Pro" alone does not answer "why can't I do this".
    render(
      <UpgradeModal
        feature={lockedFeature("mastering")}
        open
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByTestId("upgrade-modal")).toHaveTextContent(
      /Mastering is a Pro feature/i
    )
    expect(screen.getByTestId("upgrade-modal")).toHaveTextContent(
      /master your tracks to a professional loudness target/i
    )
  })

  it("offers somewhere to go", () => {
    render(
      <UpgradeModal
        feature={lockedFeature("stems")}
        open
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByRole("link", { name: /see plans/i })).toHaveAttribute(
      "href",
      "/settings/billing"
    )
  })

  it("can be dismissed without upgrading", () => {
    // It is a prompt, not a paywall — "Not now" has to be a real option.
    const onOpenChange = vi.fn()
    render(
      <UpgradeModal
        feature={lockedFeature("stems")}
        open
        onOpenChange={onOpenChange}
      />
    )

    return userEvent
      .click(screen.getByRole("button", { name: /not now/i }))
      .then(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it("still reads sensibly for a capability this build does not know", () => {
    // The server can gate something a stale frontend has no copy for; that should
    // produce a usable prompt rather than a crash in a dropdown.
    render(
      <UpgradeModal
        feature={lockedFeature("some_future_capability")}
        open
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByTestId("upgrade-modal")).toHaveTextContent(
      /This feature is a Pro feature/i
    )
  })

  it("lists what Pro actually includes", () => {
    render(<UpgradeModal feature={null} open onOpenChange={() => {}} />)

    expect(screen.getByTestId("upgrade-modal")).toHaveTextContent(
      /500 credits a month/i
    )
  })

  it("renders nothing when closed", () => {
    render(
      <UpgradeModal
        feature={lockedFeature("stems")}
        open={false}
        onOpenChange={() => {}}
      />
    )

    expect(screen.queryByTestId("upgrade-modal")).not.toBeInTheDocument()
  })
})
