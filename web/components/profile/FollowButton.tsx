"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon, CheckmarkCircle01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

// Follow/unfollow button for the public profile (US-20.5). Presentational and
// controlled: the parent owns the follow state and the derived follower count so
// the two stay in sync. `aria-pressed` exposes the toggle state to assistive tech.

export function FollowButton({
  following,
  onToggle,
}: {
  following: boolean
  onToggle: () => void
}) {
  return (
    <Button
      type="button"
      variant={following ? "secondary" : "default"}
      onClick={onToggle}
      aria-pressed={following}
      data-testid="follow-button"
    >
      <HugeiconsIcon
        icon={following ? CheckmarkCircle01Icon : Add01Icon}
        size={16}
        aria-hidden
      />
      {following ? "Following" : "Follow"}
    </Button>
  )
}
