"use client"

import { BillingSettings } from "@/components/settings/BillingSettings"
import { useRequireAuth } from "@/hooks/use-require-auth"

// US-26.3. The destination UPGRADE_URL has pointed at since US-26.2 — until now a 404.

export default function BillingSettingsPage() {
  const { accessToken } = useRequireAuth()

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Billing</h1>
        <p className="text-sm text-muted-foreground">
          Your plan, payment method, and past charges.
        </p>
      </div>
      <BillingSettings accessToken={accessToken} />
    </div>
  )
}
