"use client"

import { useRequireAuth } from "@/hooks/use-require-auth"

export default function CreatePage() {
  const { isLoading, isAuthenticated } = useRequireAuth()

  // ponytail: render nothing until authed — useRequireAuth redirects otherwise,
  // and this avoids flashing protected content during the check.
  if (isLoading || !isAuthenticated) return null

  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Create</h1>
    </div>
  )
}
