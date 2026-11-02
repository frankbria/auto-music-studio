"use client"

import Link from "next/link"

import { Button } from "@/components/ui/button"

// What the error boundaries show (#339): a plain apology, a way to retry, and somewhere to go. Never the error's
// own message, which can name internals; `digest` is the server-side reference the logs carry.
export function ErrorRecovery({
  digest,
  onRetry,
}: {
  digest?: string
  onRetry: () => void
}) {
  return (
    <div
      role="alert"
      className="mx-auto flex max-w-xl flex-col items-start gap-4 p-8"
    >
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground">
        This part of the page hit a problem. Try again, and if it keeps
        happening,{" "}
        <Link href="/support" className="underline">
          contact support
        </Link>
        {digest ? (
          <>
            {" "}
            and quote reference <code className="text-sm">{digest}</code>
          </>
        ) : null}
        .
      </p>
      <div className="flex gap-2">
        <Button onClick={onRetry}>Try again</Button>
        <Button asChild variant="outline">
          <Link href="/">Go home</Link>
        </Button>
      </div>
    </div>
  )
}
