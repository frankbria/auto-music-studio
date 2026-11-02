"use client"

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
  return (
    <html lang="en">
      <body>
        <ErrorRecovery digest={error.digest} onRetry={reset} />
      </body>
    </html>
  )
}
