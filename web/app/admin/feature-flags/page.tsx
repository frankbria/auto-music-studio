"use client"

import { FeatureFlagAdmin } from "@/components/admin/FeatureFlagAdmin"
import { useIsAdmin } from "@/hooks/use-is-admin"
import { useRequireAuth } from "@/hooks/use-require-auth"

// #342. The admin check only decides what to render; the backend's require_admin guards every flag endpoint.
export default function AdminFeatureFlagsPage() {
  const { isLoading, isAuthenticated, accessToken } = useRequireAuth()
  const { isAdmin, isLoading: adminLoading } = useIsAdmin()

  if (isLoading || !isAuthenticated || !accessToken) return null
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
          Feature flags are only available to administrators.
        </p>
      </div>
    )
  }
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Feature flags</h1>
        <p className="text-sm text-muted-foreground">
          Choose who can try each experimental feature on Labs: everyone, or
          named users. Each user still switches a feature on for themselves.
        </p>
      </div>
      <FeatureFlagAdmin token={accessToken} />
    </div>
  )
}
