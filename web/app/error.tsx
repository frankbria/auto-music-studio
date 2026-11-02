"use client"

import { useEffect } from "react"

import { ErrorRecovery } from "@/components/errors/ErrorRecovery"

// Catches an unhandled error in any page, inside the app shell, so navigation keeps working (#339).
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])
  return <ErrorRecovery digest={error.digest} onRetry={reset} />
}
