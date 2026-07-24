"use client"

import { Suspense, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon, Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { completeSoundCloudCallback } from "@/lib/distribution"
import { useAuth } from "@/hooks/use-auth"

const RETURN_TO = "/release?tab=distribute"

function CallbackHandler() {
  const { accessToken, isLoading, isAuthenticated } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [failed, setFailed] = useState(false)
  const started = useRef(false)

  const code = searchParams.get("code")
  const state = searchParams.get("state")
  // Once auth has settled without a session, the link can't complete (the backend
  // endpoints are gated) — surface the error instead of spinning forever.
  const sessionLost = !isLoading && !isAuthenticated
  const broken = failed || sessionLost || !code || !state

  useEffect(() => {
    // Exchange exactly once, and only after the access token is available (the
    // backend link endpoints are auth-gated).
    if (started.current || !code || !state || !accessToken) return
    started.current = true
    completeSoundCloudCallback(code, state, accessToken)
      .then((result) => {
        if (result.kind === "ok") router.replace(RETURN_TO)
        else setFailed(true)
      })
      .catch(() => setFailed(true))
  }, [accessToken, code, state, router])

  if (broken) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <HugeiconsIcon icon={Alert01Icon} size={32} className="text-destructive" />
        <p role="alert" className="text-sm text-muted-foreground">
          Could not connect your SoundCloud account.
        </p>
        <Button asChild variant="outline">
          <Link href={RETURN_TO}>Back to distribution</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <HugeiconsIcon icon={Loading03Icon} size={32} className="animate-spin" />
      <p className="text-sm text-muted-foreground">Connecting your SoundCloud account…</p>
    </div>
  )
}

export default function SoundCloudCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackHandler />
    </Suspense>
  )
}
