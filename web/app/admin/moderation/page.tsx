"use client"

import { ModerationDashboard } from "@/components/moderation/ModerationDashboard"
import { useIsAdmin } from "@/hooks/use-is-admin"
import { useRequireAuth } from "@/hooks/use-require-auth"

// US-27.3. The admin check here only decides what to render; every admin
// endpoint is guarded by the backend's require_admin regardless.

export default function AdminModerationPage() {
  const { isLoading, isAuthenticated, accessToken } = useRequireAuth()
  const { isAdmin, isLoading: adminLoading } = useIsAdmin()

  // useRequireAuth redirects a signed-out visitor; render nothing meanwhile.
  if (isLoading || !isAuthenticated) return null
  if (adminLoading) {
    return (
      <p className="p-8 text-sm text-muted-foreground">Checking access...</p>
    )
  }
  if (!isAdmin) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 p-8">
        <h1 className="text-2xl font-semibold">Admin access required</h1>
        <p className="text-sm text-muted-foreground">
          The moderation dashboard is only available to administrators.
        </p>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Moderation</h1>
        <p className="text-sm text-muted-foreground">
          Review reported and automatically flagged clips, act on them, and see
          every moderation action taken.
        </p>
      </div>
      <ModerationDashboard accessToken={accessToken} />
    </div>
  )
}
