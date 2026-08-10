"use client"

import { UsageSettings } from "@/components/settings/UsageSettings"
import { useRequireAuth } from "@/hooks/use-require-auth"

// US-26.5. Sits next to /settings/billing: that page answers "what am I paying?", this
// one answers "where did it go?".

export default function UsageSettingsPage() {
  const { accessToken } = useRequireAuth()

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Usage</h1>
        <p className="text-sm text-muted-foreground">
          Your credit balance, what you have spent, and on what.
        </p>
      </div>
      <UsageSettings accessToken={accessToken} />
    </div>
  )
}
