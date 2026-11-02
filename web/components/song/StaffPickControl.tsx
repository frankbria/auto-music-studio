"use client"

import { useEffect, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { StarIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import {
  getClipEngagement,
  setStaffPick,
  type ClipEngagement,
} from "@/lib/engagement"
import { cn } from "@/lib/utils"

// Admin-only song page control (#656): mark the song a staff pick for Explore, and see every count, shares
// included (shares are never shown publicly). Only rendered for an admin; the backend's require_admin guards it.

export function StaffPickControl({ clipId }: { clipId: string }) {
  const { accessToken } = useAuth()
  const [engagement, setEngagement] = useState<ClipEngagement | null>(null)
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!accessToken) return
    let active = true
    getClipEngagement(clipId, accessToken).then(
      (loaded) => active && setEngagement(loaded),
      () => active && setFailed(true)
    )
    return () => {
      active = false
    }
  }, [clipId, accessToken])

  if (!accessToken || (!engagement && !failed)) return null

  const picked = !!engagement?.staff_picked_at

  const toggle = () => {
    if (!engagement) return
    setSaving(true)
    setFailed(false)
    setStaffPick(clipId, !picked, accessToken)
      .then((staffPickedAt) =>
        setEngagement({ ...engagement, staff_picked_at: staffPickedAt })
      )
      .catch(() => setFailed(true))
      .finally(() => setSaving(false))
  }

  return (
    <div
      data-slot="staff-pick-control"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border p-3 text-sm"
    >
      <span className="font-medium">Admin</span>
      {engagement && (
        <>
          <Button
            size="sm"
            variant={picked ? "default" : "outline"}
            aria-pressed={picked}
            disabled={saving}
            onClick={toggle}
          >
            <HugeiconsIcon
              icon={StarIcon}
              size={16}
              className={cn(picked && "fill-current")}
            />
            {picked ? "Staff pick" : "Make staff pick"}
          </Button>
          <span className="text-muted-foreground tabular-nums">
            {engagement.play_count} plays · {engagement.like_count} likes ·{" "}
            {engagement.share_count} shares
          </span>
        </>
      )}
      {failed && (
        <span role="alert" className="text-destructive">
          Couldn&apos;t update the staff pick.
        </span>
      )}
    </div>
  )
}
