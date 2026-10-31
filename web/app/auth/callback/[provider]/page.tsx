"use client"

import { Suspense, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon, Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  AccountSuspendedError,
  RETURN_TO_KEY,
  safeInternalPath,
} from "@/lib/auth"
import { useAuth } from "@/hooks/use-auth"

function CallbackHandler() {
  const { completeLogin } = useAuth()
  const router = useRouter()
  const params = useParams<{ provider: string }>()
  const searchParams = useSearchParams()
  const [exchangeError, setExchangeError] = useState<string | null>(null)
  const started = useRef(false)

  const code = searchParams.get("code")
  const state = searchParams.get("state")
  const failed = exchangeError !== null || !code || !state

  useEffect(() => {
    if (started.current || !code || !state) return // exchange the code exactly once
    started.current = true
    // The return path was stashed by the login page (providers don't echo it back).
    const from = safeInternalPath(sessionStorage.getItem(RETURN_TO_KEY))
    sessionStorage.removeItem(RETURN_TO_KEY)
    completeLogin(params.provider, code, state)
      .then(() => router.replace(from))
      .catch((error: unknown) =>
        setExchangeError(
          error instanceof AccountSuspendedError
            ? error.message
            : "Sign-in could not be completed."
        )
      )
  }, [completeLogin, params.provider, router, code, state])

  if (failed) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <HugeiconsIcon
          icon={Alert01Icon}
          size={32}
          className="text-destructive"
        />
        <p role="alert" className="text-sm text-muted-foreground">
          {exchangeError ?? "Sign-in could not be completed."}
        </p>
        <Button asChild variant="outline">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <HugeiconsIcon icon={Loading03Icon} size={32} className="animate-spin" />
      <p className="text-sm text-muted-foreground">Signing you in…</p>
    </div>
  )
}

export default function CallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackHandler />
    </Suspense>
  )
}
