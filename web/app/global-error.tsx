"use client"

import { useEffect } from "react"

import { ErrorRecovery } from "@/components/errors/ErrorRecovery"

import "./globals.css"

// The last resort when the root layout itself fails (#339): it replaces the whole document, so it brings its own
// <html> and <body>.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])
  // Outside every provider, theme included: a plain document is the safe last resort.
  return (
    <html lang="en">
      <body>
        <ErrorRecovery digest={error.digest} onRetry={reset} />
      </body>
    </html>
  )
}
